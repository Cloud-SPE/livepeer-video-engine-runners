"""SGLang and vLLM-Omni video API adapter."""

from __future__ import annotations

import json
from typing import Any
import aiohttp
from video_runners.backends.base import EngineClient, _json_or_error
from video_runners.contracts import EngineError, JobRequest, JobStatus


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
            "guidance_scale": job.guidance_scale,
            "guidance_scale_2": job.guidance_scale_2,
            "flow_shift": job.flow_shift,
        }
        for name, value in fields.items():
            if value is not None:
                # Plain fields otherwise become application/x-www-form-urlencoded,
                # which SGLang does not parse as a video request.
                form.add_field(name, str(value), content_type="text/plain")
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
        async with self._http.delete(
            f"{self.spec.base_url}/v1/videos/{job_id}"
        ) as resp:
            if resp.status not in {200, 202, 204, 404}:
                raise EngineError(f"video cancellation failed: HTTP {resp.status}")
