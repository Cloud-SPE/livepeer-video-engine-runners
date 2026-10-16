"""External readiness, admission and serialized model changes."""

import argparse
import asyncio
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from video_runners.contracts import EngineError
from video_runners.lifecycle.bundled import EngineSupervisor
from video_runners.backends import engine_client
from video_runners.catalog import load_catalog
from video_runners.lifecycle.external import ExternalSupervisor
from video_runners.lifecycle.managed import ManagedSupervisor
from video_runners.origins import engine_url
from video_runners.runner.protocol import Busy
from video_runners.runner.service import Runner

MODELS, _ = load_catalog(Path(__file__).resolve().parents[2] / "models/stub.json")


def test_unavailable_owned_engine_recovers_without_operator_restart():
    async def scenario():
        observed = asyncio.Event()
        starts = []

        class Supervisor(EngineSupervisor):
            checks = 0

            async def healthy(self, client):
                self.checks += 1
                if self.checks >= 5:
                    observed.set()
                return bool(starts)

            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS["stub-wan-t2v"]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True

            async def register(_):
                pass

            runner._register = register
            monitor = asyncio.create_task(runner.monitor_engine(0.001))
            try:
                await asyncio.wait_for(observed.wait(), 1)
                assert (
                    runner.available
                ), "an idle owned engine must recover after persistent health loss"
                assert starts == ["stub-wan-t2v"]
            finally:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
                if runner.recovery:
                    await runner.recovery

    asyncio.run(scenario())


def test_health_recovery_waits_for_gpu_work_to_finish():
    async def scenario():
        observed, recovered = asyncio.Event(), asyncio.Event()
        starts = []

        class Supervisor(EngineSupervisor):
            checks = 0

            async def healthy(self, client):
                self.checks += 1
                if self.checks >= 5:
                    observed.set()
                return bool(starts)

            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS["stub-wan-t2v"]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True
            await runner.gpu.acquire()

            async def register(_):
                recovered.set()

            runner._register = register
            monitor = asyncio.create_task(runner.monitor_engine(0.001))
            try:
                await asyncio.wait_for(observed.wait(), 1)
                assert not starts, "health monitoring must not reset in-flight work"
                runner.gpu.release()
                await asyncio.wait_for(recovered.wait(), 1)
                assert runner.available
            finally:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
                if runner.recovery:
                    await runner.recovery

    asyncio.run(scenario())


def test_failed_health_reset_stays_unavailable_without_a_restart_loop(monkeypatch):
    async def scenario():
        observed = asyncio.Event()
        starts = []
        original_sleep = asyncio.sleep
        ticks = 0

        async def tick(_):
            nonlocal ticks
            if asyncio.current_task().get_name() == "health-monitor":
                ticks += 1
                if ticks == 10:
                    observed.set()
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", tick)

        class Supervisor(EngineSupervisor):
            async def healthy(self, client):
                return False

            async def start(self, spec, client):
                starts.append(spec.id)
                raise EngineError("GPU engine cannot start")

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS["stub-wan-t2v"]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True
            monitor = asyncio.create_task(
                runner.monitor_engine(0.001), name="health-monitor"
            )
            try:
                await asyncio.wait_for(observed.wait(), 1)
                assert starts == ["stub-wan-t2v"]
                assert runner.needs_reset and not runner.available
                with pytest.raises(Busy):
                    await runner.acquire_gpu()
            finally:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
                if runner.recovery:
                    await runner.recovery

    asyncio.run(scenario())


def test_explicit_managed_start_waits_for_controller_recovery(monkeypatch):
    async def scenario():
        statuses = []
        app = web.Application()
        original_sleep = asyncio.sleep

        async def fast_sleep(_):
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        async def status(_):
            phase = "recovering" if not statuses else "ready"
            statuses.append(phase)
            return web.json_response({"phase": phase, "model": "stub-wan-t2v"})

        async def activate(request):
            assert statuses == ["recovering", "ready"]
            body = await request.json()
            assert body["model"] == "stub-wan-t2v"
            return web.json_response(
                {"state": "succeeded", "endpoint": str(server.make_url("/"))}
            )

        async def healthy(_):
            return web.Response()

        app.router.add_get("/v1/status", status)
        app.router.add_post("/v1/activate", activate)
        app.router.add_get("/health", healthy)
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            supervisor = ManagedSupervisor(str(server.make_url("/")), "token", http)
            spec = MODELS["stub-wan-t2v"]
            await supervisor.start(spec, engine_client(spec, http))
            assert supervisor.running

    asyncio.run(scenario())


def test_external_engine_does_not_spawn_or_stop_processes(monkeypatch):
    async def scenario():
        async def forbidden(*args, **kwargs):
            raise AssertionError("external engines must never spawn")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
        app = web.Application()

        async def healthy(_):
            return web.Response()

        app.router.add_get("/health", healthy)
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            spec = replace(MODELS["stub-wan-t2v"], startup_timeout_s=1)
            supervisor = ExternalSupervisor(str(server.make_url("/")))
            client = engine_client(spec, http)
            await supervisor.start(spec, client)
            assert await supervisor.healthy(client)
            assert client.spec.base_url == str(server.make_url("/")).rstrip("/")
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            with pytest.raises(Busy, match="externally managed"):
                await runner.switch("stub-h3")
            await supervisor.stop()
            assert await client.healthy()

    asyncio.run(scenario())


def test_health_loss_withdraws_registration_and_recovers():
    async def scenario():
        ready = True
        app = web.Application()

        async def health(_):
            return web.Response(status=200 if ready else 503)

        app.router.add_get("/health", health)
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            spec = MODELS["stub-wan-t2v"]
            supervisor = ExternalSupervisor(str(server.make_url("/")))
            client = engine_client(spec, http)
            await supervisor.start(spec, client)
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = client
            closed = []

            class Registration:
                async def close(self):
                    closed.append(True)

            async def register(_):
                runner.registrations["test"] = Registration()

            runner._register = register
            await register(spec)
            runner.available = True
            monitor = asyncio.create_task(runner.monitor_engine(0.01))
            try:
                ready = False
                async with asyncio.timeout(2):
                    while runner.available:
                        await asyncio.sleep(0.01)
                assert closed and not runner.registrations
                with pytest.raises(Busy):
                    await runner.acquire_gpu()
                ready = True
                async with asyncio.timeout(2):
                    while not runner.available:
                        await asyncio.sleep(0.01)
                assert runner.registrations
            finally:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor

    asyncio.run(scenario())


def test_concurrent_switches_do_not_race_previous_model():
    async def scenario():
        class Supervisor(EngineSupervisor):
            async def start(self, spec, client):
                self.spec = spec

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS["stub-wan-t2v"]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)

            async def register(_):
                pass

            runner._register = register
            runner.available = True
            await runner.gpu.acquire()
            first = asyncio.create_task(runner.switch("stub-h3"))
            await asyncio.sleep(0)
            with pytest.raises(Busy, match="in progress"):
                await runner.switch("stub-wan-t2v")
            runner.gpu.release()
            await first
            assert runner.spec.id == "stub-h3"

    asyncio.run(scenario())


def test_recovery_retries_partial_registration_failure():
    async def scenario():
        class Supervisor(EngineSupervisor):
            async def healthy(self, client):
                return True

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS["stub-wan-t2v"]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            runner.client = engine_client(supervisor.spec, http)
            attempts, closed = [], []

            class Registration:
                async def close(self):
                    closed.append(True)

            async def register(_):
                attempts.append(True)
                runner.registrations["single-shot"] = Registration()
                if len(attempts) == 1:
                    raise ConnectionError("orchestrator temporarily unavailable")
                runner.registrations["persistent"] = Registration()

            runner._register = register
            monitor = asyncio.create_task(runner.monitor_engine(0.01))
            try:
                async with asyncio.timeout(2):
                    while not runner.available:
                        await asyncio.sleep(0.01)
                assert len(attempts) == 2
                assert closed == [True]
                assert set(runner.registrations) == {"single-shot", "persistent"}
            finally:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor

    asyncio.run(scenario())


@pytest.mark.parametrize("external", [False, True])
def test_uncertain_job_blocks_admission_until_owned_engine_is_reset(external):
    async def scenario():
        starts = []

        class OwnedSupervisor(EngineSupervisor):
            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec

        supervisor = (
            ExternalSupervisor("http://engine:9100") if external else OwnedSupervisor()
        )
        supervisor.spec = MODELS["stub-wan-t2v"]
        async with aiohttp.ClientSession() as http:
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = engine_client(supervisor.spec, http)
            runner.client.idle_known = False
            runner.available = True

            async def register(_):
                pass

            runner._register = register
            await runner.gpu.acquire()
            runner.release_gpu()
            with pytest.raises(Busy):
                await runner.acquire_gpu()
            await runner.recovery
            if external:
                assert runner.needs_reset and not runner.available
                assert not starts
                with pytest.raises(Busy):
                    await runner.acquire_gpu()
            else:
                assert starts == ["stub-wan-t2v"]
                assert runner.available and not runner.needs_reset
                assert runner.client.idle_known

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "file:///var/run/docker.sock",
        "http://user:password@engine",
        "http://engine/a",
        "http://engine?x=1",
        "http://engine/#x",
    ],
)
def test_endpoint_must_be_an_http_origin(url):
    with pytest.raises(ValueError):
        engine_url(url)
