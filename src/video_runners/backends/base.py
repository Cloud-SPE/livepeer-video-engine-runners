"""Asynchronous engine job contract and polling."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
import aiohttp
from video_runners.catalog import ModelSpec
from video_runners.contracts import EngineError, JobRequest, JobStatus

log = logging.getLogger("engines")
POLL_INTERVAL_S = 1.0


class EngineClient:
    """Submit, poll, fetch and cancel jobs on one engine's HTTP API."""

    def __init__(self, spec: ModelSpec, session: aiohttp.ClientSession) -> None:
        self.spec = spec
        self._http = session
        self.idle_known = True

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
        job_id = None
        last: JobStatus | None = None
        self.idle_known = False
        try:
            job_id = await self.submit(job)
            deadline = time.monotonic() + self.spec.job_timeout_s
            while True:
                status = await self.status(job_id)
                if status.state == "completed":
                    self.idle_known = True
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
            if job_id is not None and not self.idle_known:
                try:
                    await asyncio.shield(self.cancel(job_id))
                except Exception:  # best effort: the job may already be gone
                    log.warning("could not cancel engine job %s", job_id, exc_info=True)
            # A cancellation response may only mark metadata or schedule an
            # abort; it does not prove that a GPU kernel has stopped. The runner
            # must reset its owned engine before admitting another job.
            raise


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
