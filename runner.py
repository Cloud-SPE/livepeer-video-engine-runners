#!/usr/bin/env python3
"""Video engine runner: LightX2V, SGLang Diffusion or vLLM-Omni on the Livepeer network.

One process per GPU. It starts the selected model's engine as a child process
(engines.py), then registers with the orchestrator in one or both delivery modes:

  single-shot  app "video:generations/<model>"  POST /generate streams Server-Sent
                                                Events: status while the clip renders,
                                                then the MP4. Headers go out at once,
                                                so a job of several minutes never hits
                                                the proxy's header timeout, and metered
                                                pricing bills the call per second.
  persistent   app "video:sessions/<model>"     POST /session/start opens trickle
                                                channels `video` and `events`; each
                                                POST /session/jobs renders one clip
                                                into them while the client holds (and
                                                pays for) the session.

Both modes share one GPU lock. With --busy reject (the default) a request that
finds the GPU busy is refused at once (503 / 409) instead of queuing while billed.

Model switching is operator-driven: POST /admin/model on the admin port drains the
GPU, unregisters, restarts the engine with another catalog entry, and registers
again under that model's app id. The admin port is not proxied by the orchestrator.

Livepeer integration (grep `# Livepeer:`):
  1. register_runner()          — announce each delivery mode's app (startup, switch)
  2. create_trickle_channels()  — open a persistent session's video/events channels
  3. registration.close()       — deregister (switch, shutdown)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import signal
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

import aiohttp
from aiohttp import web

from engines import (
    EngineClient,
    EngineError,
    EngineSupervisor,
    JobRequest,
    JobStatus,
    ModelSpec,
    engine_client,
    load_catalog,
)
from livepeer_gateway.live_runner import (
    LiveRunnerRegistration,
    LiveRunnerSessionEvent,
    register_runner,
)

log = logging.getLogger("video-runner")

DEFAULT_PORT = 8989
DEFAULT_ADMIN_PORT = 8990
KEEPALIVE_S = 10.0
# SSE carries the MP4 as base64 in events of this many raw bytes.
SSE_CHUNK_BYTES = 512 * 1024
# The orchestrator rejects trickle segments over 10 MB, so stay well below it.
TRICKLE_SEGMENT_BYTES = 8 * 1024 * 1024
# A persistent session writes to each quiet channel at least this often (see
# Session.keep_channels_open); livepeer-node closes channels idle for 5 minutes.
CHANNEL_KEEPALIVE_S = 60.0
# App ids are "<domain>:<capability>/<model>": the capability names the runner
# endpoint family (/generate, /session/*) and the model is the catalog id.
# Clients build the same strings (client.py), so changing them is breaking.
CAPABILITIES = {"single-shot": "video:generations", "persistent": "video:sessions"}


def app_id(mode: str, model_id: str) -> str:
    return f"{CAPABILITIES[mode]}/{model_id}"


class Busy(Exception):
    """The GPU is rendering another job, or the runner is switching models."""


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


async def _retry(
    attempt: Callable[[], Awaitable[LiveRunnerRegistration]],
) -> LiveRunnerRegistration:
    """Registration retries while the orchestrator is still starting."""
    for remaining in range(9, -1, -1):
        try:
            return await attempt()
        except Exception as exc:
            if not remaining:
                raise
            log.warning("registration failed (%s); retrying in 3s", exc)
            await asyncio.sleep(3)
    raise AssertionError("unreachable")


@dataclass
class Session:
    """A persistent session's channels and its in-flight job."""

    session_id: str
    video_url: str
    events_url: str
    video: ChannelPublisher
    events: ChannelPublisher
    # The orchestrator's per-session callback URL and credential, for stop().
    control_url: str
    token: str
    job: asyncio.Task[None] | None = None
    idle_since: float = field(default_factory=time.monotonic)
    reaper: asyncio.Task[None] | None = None
    keepalive: asyncio.Task[None] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "session": self.session_id,
            "video": self.video_url,
            "events": self.events_url,
        }

    @property
    def busy(self) -> bool:
        return self.job is not None and not self.job.done()

    async def stop(self, http: aiohttp.ClientSession) -> None:
        """Ask the orchestrator to release this session (as if the client had)."""
        async with http.post(
            self.control_url + "/stop", headers={"Livepeer-Session-Token": self.token}
        ) as resp:
            if resp.status >= 400:
                log.warning(
                    "stop %s: HTTP %d %s",
                    self.session_id,
                    resp.status,
                    await resp.text(),
                )

    async def reap_when_idle(
        self, http: aiohttp.ClientSession, timeout_s: float
    ) -> None:
        """Release a session that holds the runner without rendering anything.

        Off-chain sessions never expire on their own, so a client that dies
        without releasing would otherwise keep this runner's capacity forever.
        """
        while True:
            await asyncio.sleep(min(15.0, timeout_s))
            if not self.busy and time.monotonic() - self.idle_since > timeout_s:
                log.info(
                    "session %s idle for %gs; releasing", self.session_id, timeout_s
                )
                await self.stop(http)
                return

    async def keep_channels_open(self) -> None:
        """Write an empty segment to each channel that has been quiet a while.

        livepeer-node closes a trickle channel after five minutes without a
        write, and a GPU render can take longer than that. Clients skip empty
        segments.
        """
        while True:
            await asyncio.sleep(CHANNEL_KEEPALIVE_S / 2)
            for channel in (self.video, self.events):
                if time.monotonic() - channel.last_write >= CHANNEL_KEEPALIVE_S:
                    try:
                        await channel.publish(b"")
                    except EngineError as exc:
                        log.warning("session %s keepalive: %s", self.session_id, exc)

    async def close(self) -> None:
        for task in (self.reaper, self.keepalive):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        if self.job is not None and not self.job.done():
            self.job.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.job
        with suppress(Exception):
            await self.events.close()
        with suppress(Exception):
            await self.video.close()


@dataclass
class Runner:
    args: argparse.Namespace
    models: dict[str, ModelSpec]
    http: aiohttp.ClientSession
    supervisor: EngineSupervisor = field(default_factory=EngineSupervisor)
    gpu: asyncio.Lock = field(default_factory=asyncio.Lock)
    client: EngineClient | None = None
    switching: bool = False
    registrations: dict[str, LiveRunnerRegistration] = field(default_factory=dict)
    sessions: dict[str, Session] = field(default_factory=dict)

    @property
    def spec(self) -> ModelSpec:
        assert self.supervisor.spec is not None
        return self.supervisor.spec

    # -- lifecycle -------------------------------------------------------------

    async def load(self, model_id: str) -> None:
        """Start the engine for a catalog model, then register its app ids."""
        spec = self.models[model_id]
        client = engine_client(spec, self.http)
        await self.supervisor.start(spec, client)
        self.client = client
        await self._register(spec)

    async def switch(self, model_id: str) -> None:
        if model_id not in self.models:
            raise ValueError(
                f"unknown model {model_id!r}; choose {sorted(self.models)}"
            )
        previous = self.spec.id
        if model_id == previous:
            return
        self.switching = True
        try:
            # Waits for the current job; new requests are refused meanwhile.
            async with self.gpu:
                await self._unregister()
                for session in list(self.sessions.values()):
                    await session.close()
                self.sessions.clear()
                try:
                    await self.load(model_id)
                except Exception:
                    log.exception("could not load %s; restoring %s", model_id, previous)
                    await self.load(previous)
                    raise
        finally:
            self.switching = False

    async def shutdown(self) -> None:
        await self._unregister()
        for session in list(self.sessions.values()):
            await session.close()
        await self.supervisor.stop()

    async def _register(self, spec: ModelSpec) -> None:
        common = dict(
            secret=self.args.secret,
            runner_url=self.args.runner_url,
            price=spec.price_usd_per_hour,  # USD per hour, metered per second
            label=spec.id,
            version=spec.engine,
        )
        if self.args.delivery in ("single-shot", "both"):
            self.registrations["single-shot"] = await _retry(
                lambda: register_runner(  # Livepeer: 1
                    self.args.orchestrator,
                    app=app_id("single-shot", spec.id),
                    mode="single-shot",
                    **common,
                )
            )
        if self.args.delivery in ("persistent", "both"):
            self.registrations["persistent"] = await _retry(
                lambda: register_runner(  # Livepeer: 1
                    self.args.orchestrator,
                    app=app_id("persistent", spec.id),
                    mode="persistent",
                    on_session_release=self._on_release,
                    **common,
                )
            )
        for mode, registration in self.registrations.items():
            log.info(
                "registered %s runner_id=%s app=%s",
                mode,
                registration.runner_id,
                app_id(mode, spec.id),
            )

    async def _unregister(self) -> None:
        registrations, self.registrations = self.registrations, {}
        for registration in registrations.values():
            with suppress(Exception):
                await registration.close()  # Livepeer: 3

    async def _on_release(self, event: LiveRunnerSessionEvent) -> None:
        session = self.sessions.pop(event.session_id, None)
        if session is not None:
            log.info("session %s released; closing its channels", event.session_id)
            await session.close()

    # -- GPU admission ---------------------------------------------------------

    async def acquire_gpu(self) -> EngineClient:
        """Take the GPU for one job; the caller must call release_gpu() after it.

        A persistent job releases the GPU from its own task, after the request
        that started it has returned, so this is not a context manager.
        """
        if self.switching or self.client is None:
            raise Busy("runner is switching models")
        if self.args.busy == "reject" and self.gpu.locked():
            raise Busy("GPU is rendering another job")
        await self.gpu.acquire()
        if self.switching or self.client is None:
            self.gpu.release()
            raise Busy("runner is switching models")
        return self.client

    def release_gpu(self) -> None:
        self.gpu.release()

    def job_request(self, payload: Any) -> JobRequest:
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return JobRequest.from_payload(payload, self.spec.defaults)


# -- single-shot: SSE ------------------------------------------------------------


async def _sse(resp: web.StreamResponse, event: str, data: dict[str, Any]) -> None:
    await resp.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())


async def handle_generate(request: web.Request) -> web.StreamResponse:
    runner: Runner = request.app["runner"]
    try:
        job = runner.job_request(await request.json())
    except (ValueError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    try:
        client = await runner.acquire_gpu()
    except Busy as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    resp = web.StreamResponse(
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"}
    )
    try:
        # Headers leave now: the orchestrator's 60s response-header timeout is met
        # however long the clip takes, and the stream keeps the call billed.
        await resp.prepare(request)
        await _sse(resp, "accepted", {"model": runner.spec.id})
        async for item in _with_keepalive(client.run(job)):
            if item is None:
                await resp.write(b": keepalive\n\n")
            elif isinstance(item, JobStatus):
                await _sse(
                    resp, "status", {"state": item.state, "progress": item.progress}
                )
            else:
                await _send_video(resp, item)
        await _sse(resp, "done", {})
    except ConnectionResetError:
        log.info("client went away; engine job cancelled")
    except Exception as exc:
        if not isinstance(exc, EngineError):
            log.exception("generate failed")
        with suppress(ConnectionResetError):
            await _sse(resp, "error", {"message": str(exc)[:1000]})
    finally:
        runner.release_gpu()
    return resp


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


# -- persistent: trickle -----------------------------------------------------------


def _session_id(request: web.Request) -> str:
    session_id = request.headers.get("Livepeer-Session-Id", "").strip()
    if not session_id:
        raise web.HTTPBadRequest(text="missing Livepeer-Session-Id header")
    return session_id


async def handle_session_start(request: web.Request) -> web.Response:
    runner: Runner = request.app["runner"]
    session_id = _session_id(request)
    if session_id in runner.sessions:
        return web.json_response(runner.sessions[session_id].to_json())
    registration = runner.registrations.get("persistent")
    if registration is None:
        raise web.HTTPServiceUnavailable(text="persistent delivery is not registered")

    # The request carries the orchestrator's session-control headers.
    channels = await registration.create_trickle_channels(  # Livepeer: 2
        request,
        [
            {"name": "video", "mime_type": "video/mp4"},
            {"name": "events", "mime_type": "application/jsonl"},
        ],
    )
    by_name = {channel["name"]: channel for channel in channels}
    if not {"video", "events"} <= by_name.keys():
        raise web.HTTPInternalServerError(
            text="orchestrator did not return the channels"
        )

    def internal(name: str) -> str:
        return by_name[name].get("internal_url", by_name[name]["url"])

    session = Session(
        session_id=session_id,
        video_url=by_name["video"]["url"],
        events_url=by_name["events"]["url"],
        video=ChannelPublisher(runner.http, internal("video"), "video/mp4"),
        events=ChannelPublisher(runner.http, internal("events"), "application/jsonl"),
        control_url=request.headers.get("Livepeer-Session-Control", "").rstrip("/"),
        token=request.headers.get("Livepeer-Session-Token", ""),
    )
    if runner.args.session_idle_timeout > 0 and session.control_url and session.token:
        session.reaper = asyncio.create_task(
            session.reap_when_idle(runner.http, runner.args.session_idle_timeout)
        )
    session.keepalive = asyncio.create_task(session.keep_channels_open())
    runner.sessions[session_id] = session
    log.info("started session %s", session_id)
    return web.json_response(session.to_json())


async def handle_session_job(request: web.Request) -> web.Response:
    runner: Runner = request.app["runner"]
    session = runner.sessions.get(_session_id(request))
    if session is None:
        raise web.HTTPNotFound(text="POST /session/start first")
    if session.job is not None and not session.job.done():
        raise web.HTTPConflict(text="this session already has a job running")
    try:
        job = runner.job_request(await request.json())
    except (ValueError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    try:
        client = await runner.acquire_gpu()
    except Busy as exc:
        raise web.HTTPConflict(text=str(exc)) from exc

    job_id = uuid.uuid4().hex[:12]
    session.idle_since = time.monotonic()
    session.job = asyncio.create_task(
        _render_into_session(runner, session, job_id, job, client)
    )
    return web.json_response({"job_id": job_id, "model": runner.spec.id}, status=202)


async def _render_into_session(
    runner: Runner, session: Session, job_id: str, job: JobRequest, client: EngineClient
) -> None:
    try:
        async for item in client.run(job):
            if isinstance(item, JobStatus):
                await session.events.publish_json(
                    {
                        "type": "status",
                        "job_id": job_id,
                        "state": item.state,
                        "progress": item.progress,
                    }
                )
                continue
            # The video event precedes its segments; the client reads the next
            # `segments` segments from the video channel as this job's MP4.
            parts = [
                item[i : i + TRICKLE_SEGMENT_BYTES]
                for i in range(0, len(item), TRICKLE_SEGMENT_BYTES)
            ]
            await session.events.publish_json(
                {
                    "type": "video",
                    "job_id": job_id,
                    "segments": len(parts),
                    "bytes": len(item),
                    "sha256": hashlib.sha256(item).hexdigest(),
                }
            )
            for part in parts:
                await session.video.publish(part)
        await session.events.publish_json({"type": "done", "job_id": job_id})
    except EngineError as exc:
        with suppress(EngineError):
            await session.events.publish_json(
                {"type": "error", "job_id": job_id, "message": str(exc)}
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("session %s job %s failed", session.session_id, job_id)
        with suppress(Exception):
            await session.events.publish_json(
                {"type": "error", "job_id": job_id, "message": "runner error"}
            )
    finally:
        session.idle_since = time.monotonic()
        runner.release_gpu()


# -- public info and admin -----------------------------------------------------------


async def handle_health(request: web.Request) -> web.Response:
    runner: Runner = request.app["runner"]
    # Healthy once the engine answers and the apps are registered.
    ok = runner.supervisor.running and bool(runner.registrations)
    ok = ok and not runner.switching
    return web.json_response({"ok": ok}, status=200 if ok else 503)


async def handle_models(request: web.Request) -> web.Response:
    runner: Runner = request.app["runner"]
    return web.json_response(
        {
            "current": runner.spec.id if runner.supervisor.spec else None,
            "models": [
                {
                    "id": m.id,
                    "apps": {mode: app_id(mode, m.id) for mode in CAPABILITIES},
                    "engine": m.engine,
                    "defaults": m.defaults,
                }
                for m in runner.models.values()
            ],
        }
    )


@web.middleware
async def require_admin_token(request: web.Request, handler: Any) -> web.StreamResponse:
    token = request.app["admin_token"]
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(supplied, token):
        raise web.HTTPUnauthorized(text="admin token required")
    return await handler(request)


async def handle_admin_status(request: web.Request) -> web.Response:
    runner: Runner = request.app["runner"]
    return web.json_response(
        {
            "model": runner.spec.id if runner.supervisor.spec else None,
            "switching": runner.switching,
            "gpu_busy": runner.gpu.locked(),
            "sessions": sorted(runner.sessions),
            "registrations": {
                mode: reg.runner_id for mode, reg in runner.registrations.items()
            },
            "catalog": sorted(runner.models),
        }
    )


async def handle_admin_model(request: web.Request) -> web.Response:
    runner: Runner = request.app["runner"]
    payload = await request.json()
    model_id = payload.get("model") if isinstance(payload, dict) else None
    if not isinstance(model_id, str) or model_id not in runner.models:
        raise web.HTTPBadRequest(text=f"model must be one of {sorted(runner.models)}")
    try:
        await runner.switch(model_id)
    except EngineError as exc:
        raise web.HTTPInternalServerError(text=str(exc)) from exc
    return web.json_response(
        {
            "model": runner.spec.id,
            "apps": {
                mode: app_id(mode, runner.spec.id) for mode in runner.registrations
            },
        }
    )


# -- main ------------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Video engine Live Runner.")
    parser.add_argument("--catalog", type=Path, default=Path("models/stub.json"))
    parser.add_argument(
        "--model", default="", help="Catalog id to load (default: catalog default)"
    )
    parser.add_argument("--orchestrator", default="http://localhost:8935")
    parser.add_argument(
        "--secret",
        default=os.environ.get("LIVEPEER_BOOTSTRAP_SECRET", ""),
        help="Orchestrator bootstrap secret (or LIVEPEER_BOOTSTRAP_SECRET)",
    )
    parser.add_argument("--runner-url", default=f"http://127.0.0.1:{DEFAULT_PORT}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--admin-host", default="127.0.0.1")
    parser.add_argument("--admin-port", type=int, default=DEFAULT_ADMIN_PORT)
    parser.add_argument(
        "--delivery", choices=("single-shot", "persistent", "both"), default="both"
    )
    parser.add_argument(
        "--busy",
        choices=("reject", "wait"),
        default="reject",
        help="reject: refuse requests while the GPU is busy; wait: queue them (billed)",
    )
    parser.add_argument(
        "--session-idle-timeout",
        type=float,
        default=300.0,
        help="Release a persistent session after this many idle seconds (0 = never)",
    )
    args = parser.parse_args()
    if not args.secret:
        parser.error("--secret or LIVEPEER_BOOTSTRAP_SECRET is required")
    return args


async def _serve(args: argparse.Namespace) -> None:
    models, default = load_catalog(args.catalog)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
        runner = Runner(args=args, models=models, http=http)

        public = web.Application(client_max_size=64 * 1024)
        public["runner"] = runner
        public.router.add_get("/healthz", handle_health)
        public.router.add_get("/models", handle_models)
        public.router.add_post("/generate", handle_generate)
        public.router.add_post("/session/start", handle_session_start)
        public.router.add_post("/session/jobs", handle_session_job)

        admin = web.Application(middlewares=[require_admin_token])
        admin["runner"] = runner
        admin["admin_token"] = os.environ.get("RUNNER_ADMIN_TOKEN", "")
        admin.router.add_get("/admin/status", handle_admin_status)
        admin.router.add_post("/admin/model", handle_admin_model)

        sites: list[web.AppRunner] = []
        try:
            for app, host, port in (
                (public, args.host, args.port),
                (admin, args.admin_host, args.admin_port),
            ):
                site_runner = web.AppRunner(app)
                await site_runner.setup()
                await web.TCPSite(site_runner, host, port).start()
                sites.append(site_runner)
            # SIGTERM (docker stop, systemd) must also stop the engine process
            # group and deregister, not just end this process.
            stopping = asyncio.Event()
            for signum in (signal.SIGTERM, signal.SIGINT):
                asyncio.get_running_loop().add_signal_handler(signum, stopping.set)
            # Register only once the engine answers: discovery should never list
            # a runner that cannot take a job yet.
            loading = asyncio.create_task(runner.load(args.model or default))
            stop_wait = asyncio.create_task(stopping.wait())
            await asyncio.wait(
                {loading, stop_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if loading.done():
                loading.result()
                await stop_wait
            else:
                loading.cancel()
                with suppress(asyncio.CancelledError):
                    await loading
            log.info("shutting down")
        finally:
            await runner.shutdown()
            for site_runner in sites:
                await site_runner.cleanup()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    with suppress(KeyboardInterrupt):
        asyncio.run(_serve(_parse_args()))


if __name__ == "__main__":
    main()
