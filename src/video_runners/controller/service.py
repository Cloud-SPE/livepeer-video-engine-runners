"""Serialized managed-engine operations, ownership, rollback and recovery."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import aiohttp
from video_runners.contracts import EngineError
from video_runners.controller.policy import CONTAINER_ID, IDENTIFIER, OWNER
from video_runners.controller.state import ControllerState
from video_runners.diagnostics import event, operation_id

log = logging.getLogger("engine-controller")


class Controller(ControllerState):
    async def remove(self, container_id: str) -> None:
        if (
            not CONTAINER_ID.fullmatch(container_id)
            or container_id not in self.state["containers"]
        ):
            raise EngineError("refusing unrecorded container")
        model = self.state["containers"][container_id]
        actual = await self.docker.call("GET", f"/containers/{container_id}/json")
        if actual is not None:
            if model not in self.policy.models:
                raise EngineError(
                    "recorded model removed from catalog; operator recovery required"
                )
            self.policy.verify(model, actual)
            if actual["State"].get("Running"):
                await self.docker.call(
                    "POST", f"/containers/{container_id}/stop", params={"t": "30"}
                )
            await self.docker.call("DELETE", f"/containers/{container_id}")
        del self.state["containers"][container_id]
        self.save()
        event(
            log,
            "engine.removed",
            container_id=container_id,
            model=model,
            namespace=self.policy.namespace,
        )

    async def clear(self) -> None:
        candidates = await self.docker.call(
            "GET",
            "/containers/json",
            params={
                "all": "1",
                "filters": json.dumps({"label": [f"{OWNER}={self.policy.namespace}"]}),
            },
        )
        unknown = {item["Id"] for item in candidates or []} - set(
            self.state["containers"]
        )
        if unknown:
            raise EngineError(
                "unrecorded containers claim this namespace; operator review required"
            )
        for container_id in list(self.state["containers"]):
            await self.remove(container_id)
        self.state["active"] = None
        self.save()

    async def launch(self, model: str) -> None:
        payload = self.policy.payloads[model]
        result = await self.docker.call(
            "POST",
            "/containers/create",
            body=payload,
            params={"name": self.policy.namespace + "-" + uuid.uuid4().hex[:12]},
        )
        container_id = result["Id"]
        if not CONTAINER_ID.fullmatch(container_id):
            raise EngineError("invalid container identifier from Docker")
        # Persist the daemon-issued identity BEFORE start. Unknown identities are
        # never adopted based only on forgeable labels after a crash.
        self.state["containers"][container_id] = model
        self.save()
        event(
            log,
            "engine.recorded",
            container_id=container_id,
            model=model,
            namespace=self.policy.namespace,
        )
        actual = await self.docker.call("GET", f"/containers/{container_id}/json")
        self.policy.verify(model, actual)
        await self.docker.call("POST", f"/containers/{container_id}/start")
        if self.http.connector is not None:
            self.http.connector.clear_dns_cache()
        deadline = time.monotonic() + self.policy.models[model].get("timeout", 1800)
        while time.monotonic() < deadline:
            actual = await self.docker.call("GET", f"/containers/{container_id}/json")
            if actual is None or not actual["State"].get("Running"):
                raise EngineError("engine exited during startup")
            self.policy.verify(model, actual)
            if await self.ready(model):
                self.state["active"] = model
                self.save()
                event(
                    log,
                    "engine.ready",
                    container_id=container_id,
                    model=model,
                    namespace=self.policy.namespace,
                )
                return
            await asyncio.sleep(0.5)
        raise EngineError("engine model readiness timed out")

    async def ready(self, model: str) -> bool:
        try:
            async with self.http.get(
                self.policy.endpoint(model)
                + self.policy.models[model].get("health_path", "/health"),
                timeout=aiohttp.ClientTimeout(total=5),
                allow_redirects=False,
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def recover(self) -> None:
        context = operation_id.set("recovery-" + uuid.uuid4().hex)
        event(log, "recovery.started", namespace=self.policy.namespace)
        try:
            interrupted_stop = False
            for op in self.state["operations"].values():
                if op["state"] == "running":
                    interrupted_stop = op["model"] is None
                    op.update(
                        state="failed", error="controller restarted during operation"
                    )
            self.save()
            # Reset engines before readmission: previous generation jobs may be orphaned.
            await self.clear()
            model = (
                self.state["last_good"]
                if self.state.get("enabled") and not interrupted_stop
                else None
            )
            if interrupted_stop:
                self.state["enabled"] = False
                self.save()
            if model:
                await self.launch(model)
            self.phase = "ready" if model else "idle"
        except Exception as exc:
            log.exception("engine recovery failed")
            self.phase, self.error = "error", str(exc)
        finally:
            event(
                log,
                "recovery.finished",
                namespace=self.policy.namespace,
                phase=self.phase,
            )
            operation_id.reset(context)

    def submit(self, operation_id: str, model: str | None) -> dict:
        if not IDENTIFIER.fullmatch(operation_id):
            raise ValueError("invalid operation identifier")
        operations = self.state["operations"]
        if operation_id in operations:
            if operations[operation_id]["model"] != model:
                raise ValueError("operation identifier reused with a different model")
            return operations[operation_id]
        if model is not None and model not in self.policy.models:
            raise ValueError("unknown catalog model")
        if self.phase not in {"idle", "ready"} or (self.task and not self.task.done()):
            raise RuntimeError("controller is busy or requires recovery")
        while len(operations) >= 128:
            del operations[next(iter(operations))]
        operation = {"id": operation_id, "model": model, "state": "running"}
        operations[operation_id] = operation
        self.phase = "switching"
        self.save()
        event(
            log,
            "operation.accepted",
            operation_id=operation_id,
            model=model,
            namespace=self.policy.namespace,
        )
        self.task = asyncio.create_task(self.activate(operation))
        return operation

    async def activate(self, operation: dict) -> None:
        context = operation_id.set(operation["id"])
        previous = self.state["last_good"]
        try:
            await self.clear()
            if operation["model"] is not None:
                await self.launch(operation["model"])
            if operation["model"] is not None:
                self.state["last_good"] = operation["model"]
            self.state["enabled"] = operation["model"] is not None
            self.phase = "ready" if operation["model"] else "idle"
            operation.update(
                state="succeeded",
                endpoint=(
                    self.policy.endpoint(operation["model"])
                    if operation["model"]
                    else ""
                ),
            )
        except Exception as exc:
            log.exception("engine activation failed")
            operation.update(state="failed", error=str(exc))
            try:
                await self.clear()
                if previous:
                    await self.launch(previous)
                self.phase = "ready" if previous else "idle"
                self.state["enabled"] = bool(previous)
            except Exception as rollback:
                log.exception("engine rollback failed")
                self.phase, self.error = "error", "activation and rollback failed"
                operation["error"] += f"; rollback: {rollback}"
        finally:
            self.save()
            event(
                log,
                "operation.finished",
                model=operation["model"],
                state=operation["state"],
                phase=self.phase,
                namespace=self.policy.namespace,
            )
            operation_id.reset(context)

    async def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.lease.close()
        if self.gpu_lease is not None:
            self.gpu_lease.close()
