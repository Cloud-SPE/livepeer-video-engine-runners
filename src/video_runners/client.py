#!/usr/bin/env python3
"""video-engines client: render clips through the network in either delivery mode.

  single-shot  discover -> call /generate (SSE). The orchestrator reserves a session
               for the call and releases it when the stream ends; metered pricing
               keeps the call funded for as long as the clip takes.
  persistent   discover -> reserve -> /session/start -> /session/jobs (one per clip)
               -> read the MP4s from the trickle `video` channel -> release.

Livepeer integration (grep `# Livepeer:`):
  1. runner_selector() / reserve_session()  — find the app; reserve when persistent
  2. call_runner(stream=True)               — single-shot call, paid inline
  3. TrickleSubscriber / JSONLReader        — persistent: read video + events
  4. stop_runner_session()                  — persistent: release (ends the reservation)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from livepeer_gateway.channel_reader import JSONLReader
from livepeer_gateway.errors import LivepeerGatewayError
from livepeer_gateway.http import get_json, post_json
from livepeer_gateway.live_runner import call_runner, stop_runner_session
from livepeer_gateway.selection import reserve_session, runner_selector
from livepeer_gateway.trickle_subscriber import TrickleSubscriber

DEFAULT_DISCOVERY = "http://localhost:8935/discovery"
DEFAULT_MODEL = "stub-wan-t2v"
# Must match runner protocol's CAPABILITIES: "<domain>:<capability>/<model>".
SINGLE_SHOT_APP = "video:generations/{model}"
PERSISTENT_APP = "video:sessions/{model}"

log = logging.getLogger("video-client")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render clips on a video engine runner."
    )
    parser.add_argument(
        "--prompt", default="A red fox running through fresh snow at dawn"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model id (see --list for what is served)",
    )
    parser.add_argument(
        "--mode", choices=("single-shot", "persistent"), default="single-shot"
    )
    parser.add_argument(
        "--clips", type=int, default=1, help="Clips to render (persistent)"
    )
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--num-frames", type=int)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", default="clip", help="Output file prefix")
    parser.add_argument("--discovery", default=DEFAULT_DISCOVERY)
    parser.add_argument("--signer", default="", help="Remote signer URL (paid path)")
    parser.add_argument(
        "--list", action="store_true", help="List advertised apps and exit"
    )
    return parser.parse_args()


def _job_payload(args: argparse.Namespace, index: int = 0) -> dict[str, Any]:
    payload = {
        "prompt": args.prompt,
        "width": args.width,
        "height": args.height,
        "num_frames": args.num_frames,
        "steps": args.steps,
        "seed": None if args.seed is None else args.seed + index,
    }
    return {key: value for key, value in payload.items() if value is not None}


def _save(path: Path, video: bytes, sha256: str) -> None:
    if hashlib.sha256(video).hexdigest() != sha256:
        raise LivepeerGatewayError(f"{path}: checksum mismatch")
    path.write_bytes(video)
    log.info("wrote %s (%d bytes)", path, len(video))


async def list_apps(discovery_url: str) -> None:
    entries = await get_json(discovery_url)
    for entry in entries or []:
        for runner in entry.get("runners", []):
            print(
                f"{runner.get('app')}  mode={runner.get('mode')}  "
                f"capacity={runner.get('capacity_available')}/{runner.get('capacity')}"
            )


async def single_shot(args: argparse.Namespace, signer_url: str | None) -> None:
    cursor = await runner_selector(  # Livepeer: 1
        discovery_url=args.discovery, app=SINGLE_SHOT_APP.format(model=args.model)
    )
    runner = cursor.candidates[0]
    stream = await call_runner(  # Livepeer: 2
        runner=runner,  # discovery metadata tells call_runner the price unit
        runner_url=runner.url.rstrip("/") + "/generate",
        payload=_job_payload(args),
        signer_url=signer_url,
        stream=True,
    )
    meta: dict[str, Any] = {}
    chunks: list[bytes] = []
    event = ""
    async with stream:
        async for line in stream.aiter_lines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
                continue
            if not line.startswith("data: "):
                continue
            data = json.loads(line.removeprefix("data: "))
            if event == "status":
                log.info("status %s progress=%s", data["state"], data.get("progress"))
            elif event == "accepted":
                log.info("accepted by %s", data["model"])
            elif event == "video-start":
                meta = data
            elif event == "video":
                chunks.append(base64.b64decode(data["b64"]))
            elif event == "error":
                raise LivepeerGatewayError(f"runner error: {data['message']}")
            elif event == "done":
                break
    if not meta or len(chunks) != meta["chunks"]:
        raise LivepeerGatewayError("stream ended before the video arrived")
    _save(Path(f"{args.output}.mp4"), b"".join(chunks), meta["sha256"])


async def _drain_video(
    subscriber: TrickleSubscriber, queue: asyncio.Queue[bytes | None]
) -> None:
    """Read every video segment as it is published.

    The orchestrator keeps only the last five segments of a channel, so a long clip
    must be read while it is still being written, not after its event arrives.
    """
    try:
        while (segment := await subscriber.next()) is not None:
            parts: list[bytes] = []
            try:
                reader = segment.make_reader()
                while chunk := await reader.read(chunk_size=256 * 1024):
                    parts.append(chunk)
            finally:
                await segment.close()
            # Empty segments are the runner's keepalives while it renders.
            if parts:
                await queue.put(b"".join(parts))
    finally:
        await queue.put(None)


async def _take_segments(queue: asyncio.Queue[bytes | None], count: int) -> bytes:
    parts: list[bytes] = []
    for _ in range(count):
        part = await queue.get()
        if part is None:
            raise LivepeerGatewayError("video channel closed mid-clip")
        parts.append(part)
    return b"".join(parts)


async def persistent(args: argparse.Namespace, signer_url: str | None) -> None:
    session = await reserve_session(  # Livepeer: 1
        discovery_url=args.discovery,
        app=PERSISTENT_APP.format(model=args.model),
        signer_url=signer_url,
    )
    log.info("session_id=%s app_url=%s", session.session_id, session.app_url)
    app_url = session.app_url.rstrip("/")
    try:
        # The session funds itself while held; leaving this block stops that.
        async with session:
            channels = await post_json(f"{app_url}/session/start", {})
            # New channels: read both from their first segment.
            events = JSONLReader(channels["events"])(start_seq=0)  # Livepeer: 3
            segments: asyncio.Queue[bytes | None] = asyncio.Queue()
            async with TrickleSubscriber(channels["video"], start_seq=0) as video:
                drain = asyncio.create_task(_drain_video(video, segments))
                try:
                    for index in range(args.clips):
                        job = await post_json(
                            f"{app_url}/session/jobs", _job_payload(args, index)
                        )
                        log.info(
                            "clip %d: job %s on %s", index, job["job_id"], job["model"]
                        )
                        async for message in events:
                            if message.get("job_id") != job["job_id"]:
                                continue
                            kind = message.get("type")
                            if kind == "status":
                                log.info(
                                    "status %s progress=%s",
                                    message["state"],
                                    message.get("progress"),
                                )
                            elif kind == "video":
                                clip = await _take_segments(
                                    segments, message["segments"]
                                )
                                _save(
                                    Path(f"{args.output}-{index:03d}.mp4"),
                                    clip,
                                    message["sha256"],
                                )
                            elif kind == "error":
                                raise LivepeerGatewayError(
                                    f"runner error: {message['message']}"
                                )
                            elif kind == "done":
                                break
                finally:
                    # Also on errors (e.g. a 409 busy job): a reader left
                    # waiting on the channel would block the release below.
                    drain.cancel()
                    with suppress(asyncio.CancelledError):
                        await drain
    finally:
        with suppress(Exception):
            await stop_runner_session(session)  # Livepeer: 4


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _parse_args()
    signer_url = args.signer.strip() or None
    try:
        if args.list:
            await list_apps(args.discovery)
        elif args.mode == "single-shot":
            await single_shot(args, signer_url)
        else:
            await persistent(args, signer_url)
    except LivepeerGatewayError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
