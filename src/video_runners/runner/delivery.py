"""Whole trickle segments, SSE encoding and quiet-stream keepalive."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from contextlib import suppress
from typing import Any, AsyncIterator
import aiohttp
from aiohttp import web
from video_runners.contracts import EngineError, JobStatus
from video_runners.runner.protocol import KEEPALIVE_S, SSE_CHUNK_BYTES

log = logging.getLogger("video-runner")


class ChannelPublisher:
    """Publish whole segments to one trickle channel, one POST per segment.

    The SDK's TricklePublisher opens each segment's POST before it has data, but
    aiohttp sends request headers only with the first body byte. A POST opened
    that early and left idle past livepeer-node's header timeouts (5 s on a new
    connection, 90 s on a reused one) fails, and the next write on the channel
    is lost. Clips arrive minutes apart, so each segment here is one complete
    request instead.
    """

    def __init__(self, http: aiohttp.ClientSession, url: str, mime_type: str) -> None:
        self.http = http
        self.url = url.rstrip("/")
        self.mime_type = mime_type
        self.seq = 0  # the runner creates the channel, so it starts empty
        self.last_write = time.monotonic()
        self._lock = asyncio.Lock()

    async def publish(self, data: bytes) -> None:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    async with self.http.post(
                        f"{self.url}/{self.seq}",
                        data=data,
                        headers={"Content-Type": self.mime_type},
                    ) as resp:
                        if resp.status == 200:
                            break
                        error = f"HTTP {resp.status}: {await resp.text()}"
                except aiohttp.ClientError as exc:
                    error = str(exc)
                if attempt == 2:
                    raise EngineError(f"trickle publish to {self.url} failed: {error}")
            self.seq += 1
            self.last_write = time.monotonic()

    async def publish_json(self, message: dict[str, Any]) -> None:
        await self.publish(json.dumps(message).encode() + b"\n")

    async def close(self) -> None:
        """End the channel for its subscribers."""
        async with self.http.delete(self.url):
            pass


async def _sse(resp: web.StreamResponse, event: str, data: dict[str, Any]) -> None:
    await resp.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())


async def _send_video(resp: web.StreamResponse, video: bytes) -> None:
    chunks = [
        video[i : i + SSE_CHUNK_BYTES] for i in range(0, len(video), SSE_CHUNK_BYTES)
    ]
    await _sse(
        resp,
        "video-start",
        {
            "content_type": "video/mp4",
            "bytes": len(video),
            "sha256": hashlib.sha256(video).hexdigest(),
            "chunks": len(chunks),
        },
    )
    for index, chunk in enumerate(chunks):
        await _sse(
            resp, "video", {"index": index, "b64": base64.b64encode(chunk).decode()}
        )


async def _with_keepalive(
    source: AsyncIterator[JobStatus | bytes],
) -> AsyncIterator[JobStatus | bytes | None]:
    """Yield the source's items, and None whenever it is quiet for KEEPALIVE_S."""
    iterator = source.__aiter__()
    pending: asyncio.Future[JobStatus | bytes] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_S)
            if not done:
                yield None
                continue
            finished, pending = pending, None
            try:
                item = finished.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending
        # Closing the generator cancels the engine job if it has not finished.
        with suppress(Exception):
            await iterator.aclose()  # type: ignore[attr-defined]
