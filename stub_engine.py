#!/usr/bin/env python3
"""A CPU stand-in for LightX2V, SGLang Diffusion and vLLM-Omni.

It speaks the subset of each engine's job API that engines.py uses and renders a
test-pattern MP4 instead of a generated one, after a configurable delay. It lets
the whole Livepeer path (registration, discovery, both delivery modes, model
switching) run on a machine without a suitable GPU.

  --api lightx2v  POST /v1/tasks/video/, GET /v1/tasks/{id}/status|result
  --api openai    POST /v1/videos, GET /v1/videos/{id}[/content]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import time
import uuid
from dataclasses import dataclass, field

import av
import numpy as np
from aiohttp import web


@dataclass
class Job:
    width: int
    height: int
    frames: int
    fps: int
    state: str = "queued"
    created: float = field(default_factory=time.time)
    video: bytes = b""
    task: asyncio.Task[None] | None = None


def render(job: Job) -> bytes:
    """Moving colour bars, encoded as H.264 when PyAV has it, else MPEG-4."""
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mp4") as container:
        codec = "libx264" if "libx264" in av.codecs_available else "mpeg4"
        stream = container.add_stream(codec, rate=job.fps)
        stream.width, stream.height, stream.pix_fmt = job.width, job.height, "yuv420p"
        x = np.linspace(0, 255, job.width, dtype=np.float32)
        for index in range(job.frames):
            shift = index * 4.0
            rgb = np.empty((job.height, job.width, 3), dtype=np.uint8)
            rgb[..., 0] = (x + shift) % 256
            rgb[..., 1] = (x * 0.5 + shift * 2) % 256
            rgb[..., 2] = (255 - x + shift) % 256
            frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return buffer.getvalue()


class Stub:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.jobs: dict[str, Job] = {}
        # One job at a time, like a single-GPU engine.
        self.gpu = asyncio.Lock()

    def submit(self, width: int, height: int, frames: int, fps: int) -> str:
        job_id = uuid.uuid4().hex
        job = Job(
            width=width - width % 2, height=height - height % 2, frames=frames, fps=fps
        )
        job.task = asyncio.create_task(self._run(job))
        self.jobs[job_id] = job
        return job_id

    async def _run(self, job: Job) -> None:
        async with self.gpu:
            if job.state == "cancelled":
                return
            job.state = "running"
            await asyncio.sleep(self.delay)
            job.video = await asyncio.to_thread(render, job)
            job.state = "completed"

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.state in ("completed", "cancelled"):
            return False
        job.state = "cancelled"
        if job.task is not None:
            job.task.cancel()
        print(f"cancelled job {job_id}", flush=True)
        return True

    def progress(self, job: Job) -> int:
        if job.state == "completed":
            return 100
        if job.state != "running" or self.delay <= 0:
            return 0
        return min(99, int(100 * (time.time() - job.created) / self.delay))


def _int(value: object, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def lightx2v_routes(stub: Stub, app: web.Application) -> None:
    states = {"queued": "pending", "running": "processing"}

    async def create(request: web.Request) -> web.Response:
        body = await request.json()
        size = body.get("size") or [256, 448]
        job_id = stub.submit(
            width=_int(size[1], 448),
            height=_int(size[0], 256),
            frames=_int(body.get("num_frames"), 81),
            fps=16,
        )
        return web.json_response(
            {
                "task_id": job_id,
                "task_status": "pending",
                "save_result_path": body.get("save_result_path"),
            }
        )

    async def status(request: web.Request) -> web.Response:
        job = stub.jobs.get(request.match_info["id"])
        if job is None:
            raise web.HTTPNotFound(text="Task not found")
        return web.json_response(
            {
                "task_id": request.match_info["id"],
                "status": states.get(job.state, job.state),
                "error": None,
            }
        )

    async def result(request: web.Request) -> web.Response:
        job = stub.jobs.get(request.match_info["id"])
        if job is None or job.state != "completed":
            raise web.HTTPNotFound(text="Task not completed")
        return web.Response(body=job.video, content_type="video/mp4")

    async def delete(request: web.Request) -> web.Response:
        stopped = stub.cancel(request.match_info["id"])
        return web.json_response(
            {"stop_status": "success" if stopped else "do_nothing", "reason": ""}
        )

    app.router.add_post("/v1/tasks/video/", create)
    app.router.add_get("/v1/tasks/{id}/status", status)
    app.router.add_get("/v1/tasks/{id}/result", result)
    app.router.add_delete("/v1/tasks/{id}", delete)


def openai_routes(stub: Stub, app: web.Application) -> None:
    states = {"running": "in_progress"}

    def describe(job_id: str, job: Job) -> dict[str, object]:
        return {
            "id": job_id,
            "object": "video",
            "status": states.get(job.state, job.state),
            "progress": stub.progress(job),
            "size": f"{job.width}x{job.height}",
            "created_at": int(job.created),
        }

    async def create(request: web.Request) -> web.Response:
        form = await request.post()
        width = _int(form.get("width"), 448)
        height = _int(form.get("height"), 256)
        job_id = stub.submit(
            width, height, _int(form.get("num_frames"), 81), _int(form.get("fps"), 16)
        )
        return web.json_response(describe(job_id, stub.jobs[job_id]))

    async def get(request: web.Request) -> web.Response:
        job_id = request.match_info["id"]
        job = stub.jobs.get(job_id)
        if job is None:
            raise web.HTTPNotFound(text="Video not found")
        return web.json_response(describe(job_id, job))

    async def content(request: web.Request) -> web.Response:
        job = stub.jobs.get(request.match_info["id"])
        if job is None or job.state != "completed":
            raise web.HTTPNotFound(text="Video not ready")
        return web.Response(body=job.video, content_type="video/mp4")

    async def delete(request: web.Request) -> web.Response:
        job_id = request.match_info["id"]
        stub.cancel(job_id)
        job = stub.jobs.get(job_id)
        return web.json_response(describe(job_id, job) if job else {"id": job_id})

    app.router.add_post("/v1/videos", create)
    app.router.add_get("/v1/videos/{id}", get)
    app.router.add_get("/v1/videos/{id}/content", content)
    app.router.add_delete("/v1/videos/{id}", delete)


def main() -> None:
    parser = argparse.ArgumentParser(description="CPU stand-in for a video engine.")
    parser.add_argument("--api", choices=("lightx2v", "openai"), required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument(
        "--delay", type=float, default=3.0, help="Seconds of fake rendering"
    )
    args = parser.parse_args()

    stub = Stub(args.delay)
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app.router.add_get("/health", health)
    (lightx2v_routes if args.api == "lightx2v" else openai_routes)(stub, app)
    print(f"stub {args.api} engine on {args.host}:{args.port}", flush=True)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
