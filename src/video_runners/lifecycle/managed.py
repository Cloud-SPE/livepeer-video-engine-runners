"""Authenticated model-operation client for the private controller."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from video_runners.catalog import ModelSpec
from video_runners.contracts import EngineError
from video_runners.backends.base import EngineClient
from video_runners.origins import engine_url
import uuid
import aiohttp
from video_runners.diagnostics import event

log = logging.getLogger("managed-engine")


class ManagedSupervisor:
    supports_switching = True

    def __init__(self, url: str, token: str, http: aiohttp.ClientSession) -> None:
        self.url = engine_url(url)
        self.token = token
        self.http = http
        self.spec: ModelSpec | None = None
        self.running = False

    async def request(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            async with self.http.request(
                method,
                self.url + path,
                json=body,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
            ) as response:
                data = await response.json()
                if response.status >= 400:
                    raise EngineError(
                        str(data.get("error", "controller rejected request"))
                    )
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise EngineError("engine controller unavailable") from exc

    async def preferred_model(self, timeout: float = 1800) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = await self.request("GET", "/v1/status")
            except EngineError:
                if time.monotonic() + 1 >= deadline:
                    raise
                await asyncio.sleep(1)
                continue
            if status["phase"] in {"idle", "ready"}:
                return status["model"] or status.get("selected")
            if status["phase"] == "error":
                raise EngineError(status["error"])
            await asyncio.sleep(1)
        raise EngineError("controller recovery timed out")

    async def operation(self, action: str, model: str | None, timeout: float) -> dict:
        body = {"operation_id": uuid.uuid4().hex}
        event(
            log,
            "operation.requested",
            operation_id=body["operation_id"],
            action=action,
            model=model,
        )
        if model is not None:
            body["model"] = model
        # Retry a lost response with the same key, never a second activation.
        for attempt in range(3):
            try:
                operation = await self.request("POST", "/v1/" + action, body)
                break
            except EngineError:
                event(
                    log,
                    "operation.response_unknown",
                    operation_id=body["operation_id"],
                    action=action,
                    model=model,
                )
                if attempt == 2:
                    raise
                await asyncio.sleep(1)
        deadline = time.monotonic() + timeout
        while operation["state"] == "running":
            if time.monotonic() >= deadline:
                event(
                    log,
                    "operation.timeout",
                    operation_id=body["operation_id"],
                    model=model,
                    state="unknown",
                )
                raise EngineError(
                    "controller operation timed out; reconcile before retrying"
                )
            await asyncio.sleep(0.5)
            operation = await self.request(
                "GET", "/v1/operations/" + body["operation_id"]
            )
        event(
            log,
            "operation.observed",
            operation_id=body["operation_id"],
            model=model,
            state=operation["state"],
        )
        if operation["state"] != "succeeded":
            raise EngineError(operation.get("error", "engine activation failed"))
        return operation

    async def start(self, spec: ModelSpec, client: EngineClient) -> None:
        self.running = False
        # An explicit MODEL must also wait for crash recovery or an interrupted
        # previous runner's reset, which can take minutes on a real GPU.
        await self.preferred_model(timeout=spec.startup_timeout_s * 2 + 90)
        result = await self.operation(
            "activate", spec.id, spec.startup_timeout_s * 2 + 90
        )
        self.spec = replace(spec, url=engine_url(result["endpoint"]))
        client.spec = self.spec
        self.running = await self.healthy(client)
        if not self.running:
            raise EngineError("activated engine is not ready")

    async def attach_restored(self, spec: ModelSpec, client: EngineClient) -> None:
        status = await self.request("GET", "/v1/status")
        if status["phase"] != "ready" or status["model"] != spec.id:
            raise EngineError("controller has not restored the previous model")
        self.spec = replace(spec, url=engine_url(status["endpoint"]))
        client.spec = self.spec
        self.running = await client.healthy()
        if not self.running:
            raise EngineError("restored engine is not ready")

    async def healthy(self, client: EngineClient) -> bool:
        try:
            status = await self.request("GET", "/v1/status")
            self.running = (
                self.spec is not None
                and status["phase"] == "ready"
                and status["model"] == self.spec.id
                and await client.healthy()
            )
        except EngineError:
            self.running = False
        return self.running

    async def stop(self) -> None:
        await self.operation("deactivate", None, 120)
        self.running = False
