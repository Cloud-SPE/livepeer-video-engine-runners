"""Livepeer registration, GPU admission, switching and recovery."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
import aiohttp
from livepeer_gateway.live_runner import (
    LiveRunnerRegistration,
    LiveRunnerSessionEvent,
    register_runner,
)
from video_runners.catalog import ModelSpec
from video_runners.contracts import EngineError, JobRequest
from video_runners.backends import engine_client
from video_runners.backends.base import EngineClient
from video_runners.lifecycle.bundled import EngineSupervisor
from video_runners.lifecycle.external import ExternalSupervisor
from video_runners.lifecycle.managed import ManagedSupervisor
from video_runners.runner.protocol import Busy, app_id
from video_runners.runner.sessions import Session
from video_runners.runner.metrics import Metrics

log = logging.getLogger("video-runner")
FORCE_STOP_TIMEOUT_S = 120.0


async def _retry(
    attempt: Callable[[], Awaitable[LiveRunnerRegistration]],
) -> LiveRunnerRegistration:
    """Registration retries while the orchestrator is still starting."""
    for remaining in range(9, -1, -1):
        try:
            return await attempt()
        except Exception as exc:
            if not remaining:
                raise
            log.warning("registration failed (%s); retrying in 3s", exc)
            await asyncio.sleep(3)
    raise AssertionError("unreachable")


@dataclass
class Runner:
    args: argparse.Namespace
    models: dict[str, ModelSpec]
    http: aiohttp.ClientSession
    supervisor: EngineSupervisor | ExternalSupervisor | ManagedSupervisor = field(
        default_factory=EngineSupervisor
    )
    gpu: asyncio.Lock = field(default_factory=asyncio.Lock)
    client: EngineClient | None = None
    switching: bool = False
    registrations: dict[str, LiveRunnerRegistration] = field(default_factory=dict)
    sessions: dict[str, Session] = field(default_factory=dict)
    available: bool = False
    lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    needs_reset: bool = False
    closing: bool = False
    recovery: asyncio.Task | None = None
    active_job: asyncio.Task | None = None
    switch_task: asyncio.Task | None = None
    metrics: Metrics = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.metrics = Metrics(self)

    @property
    def spec(self) -> ModelSpec:
        assert self.supervisor.spec is not None
        return self.supervisor.spec

    # -- lifecycle -------------------------------------------------------------

    async def load(self, model_id: str) -> None:
        """Start the engine for a catalog model, then register its app ids."""
        spec = self.models[model_id]
        client = engine_client(spec, self.http)
        await self.supervisor.start(spec, client)
        self.client = client
        await self._register(spec)
        self.needs_reset = False
        self.available = True

    async def switch(self, model_id: str, *, force: bool = False) -> None:
        if self.closing:
            raise Busy("runner is shutting down")
        if model_id not in self.models:
            raise ValueError(f"unknown model {model_id!r}")
        if not self.supervisor.supports_switching:
            raise Busy("switching is disabled for externally managed engines")
        if self.lifecycle_lock.locked():
            raise Busy("a model switch or recovery is in progress")
        async with self.lifecycle_lock:
            previous = self.spec.id
            if model_id == previous and self.available and not force:
                return
            self.switch_task = asyncio.current_task()
            was_available = self.available
            self.switching = True
            self.available = False
            acquired = False
            started, outcome = time.monotonic(), "failed"
            mode = "force" if force else "graceful"
            try:
                if force:
                    # A cancellation acknowledgement does not establish idle.
                    # Confirm owned-engine termination before loading anything.
                    self.needs_reset = True
                    try:
                        async with asyncio.timeout(FORCE_STOP_TIMEOUT_S):
                            task = self.active_job
                            if task is not None and not task.done():
                                task.cancel()
                            await self.supervisor.stop()
                            if task is not None:
                                await asyncio.wait({task})
                                with suppress(asyncio.CancelledError, Exception):
                                    task.result()
                                if self.active_job is task and self.gpu.locked():
                                    # A persistent task cancelled before its first
                                    # instruction cannot run its release finally.
                                    self.release_gpu()
                            await self.gpu.acquire()
                            acquired = True
                    except (TimeoutError, EngineError) as exc:
                        raise EngineError(
                            "forced switch could not confirm engine stop; recovery required"
                        ) from exc
                if not acquired:
                    try:
                        async with asyncio.timeout(
                            getattr(self.args, "switch_drain_timeout", 120.0)
                        ):
                            await self.gpu.acquire()
                    except TimeoutError as exc:
                        outcome = "drain_timeout"
                        raise Busy(
                            "model switch drain timed out; active job was left running"
                        ) from exc
                    acquired = True
                await self._unregister()
                for session in list(self.sessions.values()):
                    await session.close()
                self.sessions.clear()
                try:
                    await self.load(model_id)
                except Exception:
                    log.exception("could not load %s; restoring %s", model_id, previous)
                    if isinstance(self.supervisor, ManagedSupervisor):
                        # The failed operation becomes visible before the
                        # controller finishes loading the previous GPU model.
                        restored = await self.supervisor.preferred_model(
                            timeout=self.models[previous].startup_timeout_s + 90
                        )
                        if restored != previous:
                            raise EngineError(
                                "controller has not restored previous model"
                            )
                        client = engine_client(self.models[previous], self.http)
                        await self.supervisor.attach_restored(
                            self.models[previous], client
                        )
                        self.client = client
                        await self._register(self.models[previous])
                        self.needs_reset = False
                        self.available = True
                    else:
                        await self.load(previous)
                    raise
                outcome = "succeeded"
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            finally:
                self.metrics.switches.labels(model_id, mode, outcome).inc()
                self.metrics.switch_duration.labels(model_id, mode, outcome).observe(
                    time.monotonic() - started
                )
                if acquired:
                    self.gpu.release()
                else:
                    self.available = (
                        was_available and not self.needs_reset and not self.closing
                    )
                self.switching = False
                self.switch_task = None

    async def monitor_engine(self, interval: float = 2) -> None:
        failures = 0
        while True:
            await asyncio.sleep(interval)
            async with self.lifecycle_lock:
                if self.client is None or self.needs_reset:
                    continue
                try:
                    healthy = await self.supervisor.healthy(self.client)
                    if self.gpu.locked():
                        # Unregistering also cancels the node's active requests.
                        # Keep their registration through a transient probe loss;
                        # the job deadline and uncertain-job recovery still apply.
                        self.available = healthy and bool(self.registrations)
                        failures = 0 if healthy else failures + 1
                        continue
                    if not healthy:
                        failures += 1
                        self.available = False
                        await self._unregister()
                        if (
                            failures >= 3
                            and not self.gpu.locked()
                            and not isinstance(self.supervisor, ExternalSupervisor)
                            and not self.closing
                        ):
                            # One owned reset after persistent health loss. A
                            # failed reset keeps needs_reset set and fails closed.
                            self.needs_reset = True
                            self.recovery = asyncio.create_task(
                                self.recover_uncertain_job(self.client)
                            )
                    elif not self.available or not self.registrations:
                        failures = 0
                        await self._unregister()
                        await self._register(self.spec)
                        self.available = True
                    else:
                        failures = 0
                except Exception:
                    log.exception(
                        "engine health or registration check failed; retrying"
                    )
                    self.available = False
                    if not self.gpu.locked():
                        await self._unregister()

    async def shutdown(self) -> None:
        self.closing = True
        self.available = False
        for task in (self.recovery, self.switch_task):
            if (
                task is not None
                and task is not asyncio.current_task()
                and not task.done()
            ):
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
        async with self.lifecycle_lock:
            await self._unregister()
            for session in list(self.sessions.values()):
                await session.close()
            await self.supervisor.stop()

    async def _register(self, spec: ModelSpec) -> None:
        common = dict(
            secret=self.args.secret,
            runner_url=self.args.runner_url,
            price=spec.price_usd_per_hour,  # USD per hour, metered per second
            label=spec.id,
            version=spec.engine,
        )
        if self.args.delivery in ("single-shot", "both"):
            self.registrations["single-shot"] = await _retry(
                lambda: register_runner(  # Livepeer: 1
                    self.args.orchestrator,
                    app=app_id("single-shot", spec.id),
                    mode="single-shot",
                    **common,
                )
            )
        if self.args.delivery in ("persistent", "both"):
            self.registrations["persistent"] = await _retry(
                lambda: register_runner(  # Livepeer: 1
                    self.args.orchestrator,
                    app=app_id("persistent", spec.id),
                    mode="persistent",
                    on_session_release=self._on_release,
                    **common,
                )
            )
        for mode, registration in self.registrations.items():
            log.info(
                "registered %s runner_id=%s app=%s",
                mode,
                registration.runner_id,
                app_id(mode, spec.id),
            )

    async def _unregister(self) -> None:
        registrations, self.registrations = self.registrations, {}
        for registration in registrations.values():
            with suppress(Exception):
                await registration.close()  # Livepeer: 3

    async def _on_release(self, event: LiveRunnerSessionEvent) -> None:
        session = self.sessions.pop(event.session_id, None)
        if session is not None:
            log.info("session %s released; closing its channels", event.session_id)
            await session.close()

    # -- GPU admission ---------------------------------------------------------

    async def acquire_gpu(self) -> EngineClient:
        """Take the GPU for one job; the caller must call release_gpu() after it.

        A persistent job releases the GPU from its own task, after the request
        that started it has returned, so this is not a context manager.
        """
        if self.switching or self.client is None or not self.available:
            self.metrics.refusals.labels(
                self.supervisor.spec.id if self.supervisor.spec else "", "unavailable"
            ).inc()
            raise Busy("runner is switching models")
        if self.args.busy == "reject" and self.gpu.locked():
            self.metrics.refusals.labels(self.spec.id, "busy").inc()
            raise Busy("GPU is rendering another job")
        await self.gpu.acquire()
        if self.switching or self.client is None or not self.available:
            self.gpu.release()
            self.metrics.refusals.labels(self.spec.id, "unavailable").inc()
            raise Busy("runner is switching models")
        return self.client

    def release_gpu(self) -> None:
        self.active_job = None
        if self.client is not None and not self.client.idle_known and not self.closing:
            self.needs_reset = True
            self.available = False
            if not self.switching:
                self.recovery = asyncio.create_task(
                    self.recover_uncertain_job(self.client)
                )
        self.gpu.release()

    async def recover_uncertain_job(self, client: EngineClient) -> None:
        async with self.lifecycle_lock:
            # An explicit model switch may already have replaced this engine.
            if self.client is not client or not self.needs_reset:
                return
            await self._unregister()
            if isinstance(self.supervisor, ExternalSupervisor):
                log.error(
                    "engine idle state unknown; restart the external engine and runner"
                )
                return
            self.switching = True
            model, outcome = self.spec.id, "failed"
            try:
                for session in list(self.sessions.values()):
                    await session.close()
                self.sessions.clear()
                await self.load(model)
                outcome = "succeeded"
            except Exception:
                log.exception("engine reset after interrupted generation failed")
                self.available = False
            finally:
                self.metrics.restarts.labels(model, outcome).inc()
                self.switching = False

    def job_request(self, payload: Any) -> JobRequest:
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        job = JobRequest.from_payload(payload, self.spec.defaults)
        if job.negative_prompt and not self.spec.supports_negative_prompt:
            raise ValueError("this model does not support a negative prompt")
        return job
