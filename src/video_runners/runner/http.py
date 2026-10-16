"""Generation/session routes and token-authenticated admin handlers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from contextlib import suppress
from typing import Any
from aiohttp import web
from video_runners.contracts import EngineError, JobRequest, JobStatus
from video_runners.backends.base import EngineClient
from video_runners.runner.delivery import (
    ChannelPublisher,
    _sse,
    _send_video,
    _with_keepalive,
)
from video_runners.runner.protocol import (
    Busy,
    CAPABILITIES,
    TRICKLE_SEGMENT_BYTES,
    app_id,
)
from video_runners.runner.service import Runner
from video_runners.runner.sessions import Session

log = logging.getLogger("video-runner")


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


async def handle_health(request: web.Request) -> web.Response:
    runner: Runner = request.app["runner"]
    # Healthy once the engine answers and the apps are registered.
    ok = runner.available and runner.supervisor.running and bool(runner.registrations)
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
            "recovery_required": runner.needs_reset,
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
    except Busy as exc:
        raise web.HTTPConflict(text=str(exc)) from exc
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
