"""Video engine backends, the model catalog, and the engine process supervisor.

Nothing here knows about Livepeer. runner.py puts it on the network.

Each engine is an off-the-shelf server with an asynchronous job API:

  lightx2v       POST /v1/tasks/video/  -> GET /v1/tasks/{id}/status -> /result
  openai-videos  POST /v1/videos        -> GET /v1/videos/{id}       -> /content
                 (the shape shared by SGLang Diffusion and vLLM-Omni)

The supervisor runs the selected model's engine as a child process, so switching
models means stopping one engine process and starting another.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

log = logging.getLogger("engines")

ENGINE_KINDS = frozenset({"lightx2v", "openai-videos"})
MODEL_ID = re.compile(r"[a-z0-9][a-z0-9.-]*")
POLL_INTERVAL_S = 1.0
# Each engine's own log tail is kept for error messages when it fails to start.
LOG_TAIL_LINES = 40


class EngineError(RuntimeError):
    """The engine rejected a job, failed it, or is not running."""


@dataclass(frozen=True)
class ModelSpec:
    """One catalog entry: which engine to run, with what, for which model.

    `id` names the model, not the engine: the runner advertises it in its app
    ids, so the same model served by two engines is one offering on the network.
    """

    id: str
    engine: str
    command: tuple[str, ...]
    port: int
    health_path: str = "/health"
    startup_timeout_s: float = 1800.0
    job_timeout_s: float = 1800.0
    price_usd_per_hour: float = 0.0
    env: dict[str, str] = field(default_factory=dict)
    # Request fields used when the client leaves them out. Each engine reads only
    # the ones its API supports (LightX2V takes step count from its startup config).
    defaults: dict[str, Any] = field(default_factory=dict)
    # openai-videos only: the `model` form field, when the server wants one.
    served_model: str = ""

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def load_catalog(path: Path) -> tuple[dict[str, ModelSpec], str]:
    """Read models.json: {"default": id, "models": [ModelSpec fields...]}."""
    raw = json.loads(path.read_text())
    models: dict[str, ModelSpec] = {}
    for entry in raw["models"]:
        spec = ModelSpec(
            id=entry["id"],
            engine=entry["engine"],
            command=tuple(entry["command"]),
            port=int(entry["port"]),
            health_path=entry.get("health_path", "/health"),
            startup_timeout_s=float(entry.get("startup_timeout_s", 1800)),
            job_timeout_s=float(entry.get("job_timeout_s", 1800)),
            price_usd_per_hour=float(entry.get("price_usd_per_hour", 0)),
            env={k: str(v) for k, v in entry.get("env", {}).items()},
            defaults=dict(entry.get("defaults", {})),
            served_model=entry.get("served_model", ""),
        )
        if not MODEL_ID.fullmatch(spec.id):
            raise ValueError(
                f"model id {spec.id!r} must be lowercase letters, digits, '.', '-'"
            )
        if spec.engine not in ENGINE_KINDS:
            raise ValueError(f"{spec.id}: engine must be one of {sorted(ENGINE_KINDS)}")
        if spec.id in models:
            raise ValueError(f"duplicate model id {spec.id!r}")
        models[spec.id] = spec
    default = raw.get("default") or next(iter(models))
    if default not in models:
        raise ValueError(f"default model {default!r} is not in the catalog")
    return models, default


@dataclass
class JobRequest:
    """A generation request after the catalog defaults are applied."""

    prompt: str
    negative_prompt: str = ""
    width: int | None = None
    height: int | None = None
    num_frames: int | None = None
    fps: int | None = None
    steps: int | None = None
    seed: int | None = None

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], defaults: dict[str, Any]
    ) -> JobRequest:
        merged = {**defaults, **{k: v for k, v in payload.items() if v is not None}}
        prompt = merged.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        if len(prompt) > 4000:
            raise ValueError("prompt must be at most 4000 characters")

        def _int(name: str) -> int | None:
            value = merged.get(name)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            return value

        return cls(
            prompt=prompt.strip(),
            negative_prompt=str(merged.get("negative_prompt", "")),
            width=_int("width"),
            height=_int("height"),
            num_frames=_int("num_frames"),
            fps=_int("fps"),
            steps=_int("steps"),
            seed=_int("seed"),
        )


@dataclass(frozen=True)
class JobStatus:
    state: str  # queued | running | completed | failed | cancelled
    progress: int | None = None
    error: str = ""


class EngineClient:
    """Submit, poll, fetch and cancel jobs on one engine's HTTP API."""

    def __init__(self, spec: ModelSpec, session: aiohttp.ClientSession) -> None:
        self.spec = spec
        self._http = session

    async def healthy(self) -> bool:
        try:
            async with self._http.get(
                self.spec.base_url + self.spec.health_path,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def submit(self, job: JobRequest) -> str:
        raise NotImplementedError

    async def status(self, job_id: str) -> JobStatus:
        raise NotImplementedError

    async def fetch(self, job_id: str) -> bytes:
        raise NotImplementedError

    async def cancel(self, job_id: str) -> None:
        raise NotImplementedError

    async def run(self, job: JobRequest) -> AsyncIterator[JobStatus | bytes]:
        """Submit a job, yield each status change, then yield the MP4 bytes.

        Cancelling the consumer cancels the engine job as well, so an abandoned
        request does not keep the GPU busy.
        """
        job_id = await self.submit(job)
        deadline = time.monotonic() + self.spec.job_timeout_s
        last: JobStatus | None = None
        try:
            while True:
                status = await self.status(job_id)
                if status != last:
                    last = status
                    yield status
                if status.state == "completed":
                    break
                if status.state in ("failed", "cancelled"):
                    raise EngineError(status.error or f"engine job {status.state}")
                if time.monotonic() > deadline:
                    raise EngineError(f"job exceeded {self.spec.job_timeout_s:g}s")
                await asyncio.sleep(POLL_INTERVAL_S)
            yield await self.fetch(job_id)
        except BaseException:
            if last is None or last.state != "completed":
                try:
                    await asyncio.shield(self.cancel(job_id))
                except Exception:  # best effort: the job may already be gone
                    log.warning("could not cancel engine job %s", job_id, exc_info=True)
            raise


class LightX2VClient(EngineClient):
    """LightX2V's `python -m lightx2v.server` task API."""

    _STATES = {
        "pending": "queued",
        "processing": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }

    async def submit(self, job: JobRequest) -> str:
        body: dict[str, Any] = {
            "prompt": job.prompt,
            "negative_prompt": job.negative_prompt,
            # Without a result path the server skips saving and /result 404s.
            "save_result_path": f"livepeer-{time.time_ns()}.mp4",
        }
        if job.width and job.height:
            body["size"] = [job.height, job.width]
        if job.num_frames:
            body["num_frames"] = job.num_frames
        if job.seed is not None:
            body["seed"] = job.seed
        async with self._http.post(
            self.spec.base_url + "/v1/tasks/video/", json=body
        ) as resp:
            data = await _json_or_error(resp)
        return str(data["task_id"])

    async def status(self, job_id: str) -> JobStatus:
        async with self._http.get(
            f"{self.spec.base_url}/v1/tasks/{job_id}/status"
        ) as resp:
            data = await _json_or_error(resp)
        state = self._STATES.get(str(data.get("status")), "running")
        return JobStatus(state=state, error=str(data.get("error") or ""))

    async def fetch(self, job_id: str) -> bytes:
        async with self._http.get(
            f"{self.spec.base_url}/v1/tasks/{job_id}/result"
        ) as resp:
            if resp.status != 200:
                raise EngineError(f"result fetch failed: HTTP {resp.status}")
            return await resp.read()

    async def cancel(self, job_id: str) -> None:
        async with self._http.delete(f"{self.spec.base_url}/v1/tasks/{job_id}"):
            pass


class OpenAIVideosClient(EngineClient):
    """The OpenAI-style /v1/videos job API of SGLang Diffusion and vLLM-Omni."""

    _STATES = {
        "queued": "queued",
        "in_progress": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }

    async def submit(self, job: JobRequest) -> str:
        # Multipart form: vLLM-Omni documents only form fields, and SGLang accepts both.
        form = aiohttp.FormData()
        fields: dict[str, Any] = {
            "prompt": job.prompt,
            "model": self.spec.served_model or None,
            "negative_prompt": job.negative_prompt or None,
            "width": job.width,
            "height": job.height,
            "size": f"{job.width}x{job.height}" if job.width and job.height else None,
            "num_frames": job.num_frames,
            "fps": job.fps,
            "num_inference_steps": job.steps,
            "seed": job.seed,
        }
        for name, value in fields.items():
            if value is not None:
                form.add_field(name, str(value))
        async with self._http.post(
            self.spec.base_url + "/v1/videos", data=form
        ) as resp:
            data = await _json_or_error(resp)
        return str(data["id"])

    async def status(self, job_id: str) -> JobStatus:
        async with self._http.get(f"{self.spec.base_url}/v1/videos/{job_id}") as resp:
            data = await _json_or_error(resp)
        state = self._STATES.get(str(data.get("status")), "running")
        error = data.get("error")
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error)
        progress = data.get("progress")
        return JobStatus(
            state=state,
            progress=progress if isinstance(progress, int) else None,
            error=str(error or ""),
        )

    async def fetch(self, job_id: str) -> bytes:
        async with self._http.get(
            f"{self.spec.base_url}/v1/videos/{job_id}/content"
        ) as resp:
            if resp.status != 200:
                raise EngineError(f"content fetch failed: HTTP {resp.status}")
            return await resp.read()

    async def cancel(self, job_id: str) -> None:
        async with self._http.delete(f"{self.spec.base_url}/v1/videos/{job_id}"):
            pass


def engine_client(spec: ModelSpec, session: aiohttp.ClientSession) -> EngineClient:
    if spec.engine == "lightx2v":
        return LightX2VClient(spec, session)
    return OpenAIVideosClient(spec, session)


async def _json_or_error(resp: aiohttp.ClientResponse) -> dict[str, Any]:
    text = await resp.text()
    if resp.status >= 400:
        raise EngineError(f"engine HTTP {resp.status}: {text[:500]}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EngineError(f"engine returned non-JSON: {text[:200]}") from exc
    if not isinstance(data, dict):
        raise EngineError("engine returned a non-object JSON response")
    return data


class EngineSupervisor:
    """Run one model's engine as a child process and swap it on request."""

    def __init__(self) -> None:
        self.spec: ModelSpec | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._log_task: asyncio.Task[None] | None = None
        self._tail: list[str] = []

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self, spec: ModelSpec, client: EngineClient) -> None:
        """Launch the engine and wait until its health endpoint answers 200."""
        await self.stop()
        self.spec = spec
        self._tail = []
        log.info("starting engine for %s: %s", spec.id, " ".join(spec.command))
        self._process = await asyncio.create_subprocess_exec(
            *spec.command,
            env={**os.environ, **spec.env},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            # Own process group, so stop() also ends the engine's worker processes.
            start_new_session=True,
        )
        self._log_task = asyncio.create_task(self._pump_logs(spec.id))
        deadline = time.monotonic() + spec.startup_timeout_s
        while time.monotonic() < deadline:
            if not self.running:
                raise EngineError(
                    f"engine for {spec.id} exited during startup:\n"
                    + "\n".join(self._tail)
                )
            if await client.healthy():
                log.info("engine for %s is ready", spec.id)
                return
            await asyncio.sleep(2.0)
        await self.stop()
        raise EngineError(
            f"engine for {spec.id} not ready after {spec.startup_timeout_s:g}s"
        )

    async def stop(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            log.info("stopping engine for %s", self.spec.id if self.spec else "?")
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=30)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        if self._log_task is not None:
            self._log_task.cancel()
            self._log_task = None

    async def _pump_logs(self, model_id: str) -> None:
        assert self._process is not None and self._process.stdout is not None
        async for raw in self._process.stdout:
            line = raw.decode(errors="replace").rstrip()
            self._tail = (self._tail + [line])[-LOG_TAIL_LINES:]
            log.info("[%s] %s", model_id, line)
