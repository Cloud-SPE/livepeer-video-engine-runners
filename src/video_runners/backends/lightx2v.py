"""LightX2V task API adapter."""

from __future__ import annotations

import time
from typing import Any
from video_runners.backends.base import EngineClient, _json_or_error
from video_runners.contracts import EngineError, JobRequest, JobStatus


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
            # Without a result path the server skips saving and /result 404s.
            "save_result_path": f"livepeer-{time.time_ns()}.mp4",
        }
        if self.spec.supports_negative_prompt:
            body["negative_prompt"] = job.negative_prompt
        elif job.negative_prompt:
            raise EngineError("this model does not support a negative prompt")
        if self.spec.task:
            body["task"] = self.spec.task
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
        async with self._http.delete(f"{self.spec.base_url}/v1/tasks/{job_id}") as resp:
            if resp.status not in {200, 202, 204, 404}:
                raise EngineError(f"task cancellation failed: HTTP {resp.status}")
