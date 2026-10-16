"""Runner-owned engine process-group supervision."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from video_runners.catalog import ModelSpec
from video_runners.contracts import EngineError
from video_runners.backends.base import EngineClient

log = logging.getLogger("engines")
LOG_TAIL_LINES = 40


class EngineSupervisor:
    """Run one model's engine as a child process and swap it on request."""

    def __init__(self) -> None:
        self.spec: ModelSpec | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._log_task: asyncio.Task[None] | None = None
        self._tail: list[str] = []

    supports_switching = True

    async def healthy(self, client: EngineClient) -> bool:
        return self.running and await client.healthy()

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
