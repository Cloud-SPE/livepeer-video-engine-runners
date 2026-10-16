"""Health supervision of an operator-owned engine."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from video_runners.catalog import ModelSpec
from video_runners.contracts import EngineError
from video_runners.backends.base import EngineClient
from video_runners.origins import engine_url


class ExternalSupervisor:
    supports_switching = False

    def __init__(self, url: str) -> None:
        self.url = engine_url(url)
        self.spec: ModelSpec | None = None
        self.running = False

    async def start(self, spec: ModelSpec, client: EngineClient) -> None:
        self.running = False
        self.spec = replace(spec, url=self.url)
        client.spec = self.spec
        deadline = time.monotonic() + spec.startup_timeout_s
        while time.monotonic() < deadline:
            if await client.healthy():
                self.running = True
                return
            await asyncio.sleep(1)
        raise EngineError("external engine did not become ready")

    async def healthy(self, client: EngineClient) -> bool:
        self.running = await client.healthy()
        return self.running

    async def stop(self) -> None:
        self.running = False  # The external deployment owns its engine.
