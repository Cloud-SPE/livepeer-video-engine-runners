"""Bounded graceful switching and explicit interruption of owned work."""

import argparse
import asyncio
from contextlib import suppress
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from prometheus_client import generate_latest

from video_runners.backends import engine_client
from video_runners.catalog import load_catalog
from video_runners.lifecycle.bundled import EngineSupervisor
from video_runners.runner.protocol import Busy
from video_runners.runner.service import Runner
from video_runners.runner import app
import video_runners.runner.service as service
from video_runners.contracts import EngineError
from video_runners.runner.http import handle_session_job
from video_runners.runner.sessions import Session

MODELS, DEFAULT = load_catalog(Path(__file__).resolve().parents[2] / "models/stub.json")


def test_shutdown_cancels_a_pending_force_switch_before_it_can_activate_a_replacement():
    async def scenario():
        stopping, may_stop = asyncio.Event(), asyncio.Event()
        starts, stops = [], []

        class Supervisor(EngineSupervisor):
            def __init__(self):
                super().__init__()
                self.engine_running = True

            @property
            def running(self):
                return self.engine_running

            async def stop(self):
                stops.append(True)
                if len(stops) == 1:
                    stopping.set()
                    await may_stop.wait()
                self.engine_running = False

            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec
                self.engine_running = True

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True

            async def register(_):
                pass

            runner._register = register
            forcing = asyncio.create_task(runner.switch("stub-h3", force=True))
            await asyncio.wait_for(stopping.wait(), 1)
            shutdown = asyncio.create_task(runner.shutdown())
            await asyncio.sleep(0)
            may_stop.set()
            await asyncio.wait_for(
                asyncio.gather(forcing, shutdown, return_exceptions=True), 1
            )
            assert not starts, "shutdown must prevent replacement activation"
            assert not supervisor.running and not runner.available
            assert not runner.gpu.locked()

    asyncio.run(scenario())


def test_model_switching_cannot_restart_an_engine_after_shutdown_begins():
    async def scenario():
        starts = []

        class Supervisor(EngineSupervisor):
            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            runner.closing = True

            async def register(_):
                pass

            runner._register = register
            with pytest.raises(Busy, match="shutting down"):
                await runner.switch("stub-h3", force=True)
            assert not starts

    asyncio.run(scenario())


def test_graceful_switch_timeout_preserves_active_work_and_registration():
    async def scenario():
        starts = []

        class Supervisor(EngineSupervisor):
            async def start(self, spec, client):
                starts.append(spec.id)

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject", switch_drain_timeout=0.01),
                MODELS,
                http,
                supervisor=supervisor,
            )
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True
            registration = object()
            runner.registrations["single-shot"] = registration
            await runner.gpu.acquire()
            try:
                with pytest.raises(Busy, match="drain timed out"):
                    await asyncio.wait_for(runner.switch("stub-h3"), 0.5)
                assert runner.gpu.locked(), "the active job retains its GPU"
                assert runner.registrations["single-shot"] is registration
                assert runner.available and not runner.switching
                assert not starts and runner.spec.id == DEFAULT
                assert (
                    'video_runner_switches_total{mode="graceful",model="stub-h3",outcome="drain_timeout"} 1.0'
                    in generate_latest(runner.metrics.registry).decode()
                )
            finally:
                runner.gpu.release()

    asyncio.run(scenario())


def test_force_switch_releases_a_persistent_job_cancelled_before_its_task_starts():
    async def scenario():
        class Supervisor(EngineSupervisor):
            async def stop(self):
                pass

            async def start(self, spec, client):
                self.spec = spec

        class Channel:
            async def close(self):
                pass

        class Request:
            headers = {"Livepeer-Session-Id": "session"}

            async def json(self):
                return {"prompt": "test"}

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject", switch_drain_timeout=0.01),
                MODELS,
                http,
                supervisor=supervisor,
            )
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True
            runner.sessions["session"] = Session(
                "session", "", "", Channel(), Channel(), "", ""
            )

            async def register(_):
                pass

            runner._register = register
            request = Request()
            request.app = {"runner": runner}
            assert (await handle_session_job(request)).status == 202
            # No event-loop yield before forcing; the admitted task has not run.
            await asyncio.wait_for(runner.switch("stub-h3", force=True), 0.5)
            assert runner.available and runner.spec.id == "stub-h3"
            assert not runner.gpu.locked() and runner.active_job is None

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["unavailable", "timeout"])
def test_unconfirmed_force_stop_keeps_admission_closed_without_activation(
    monkeypatch, failure
):
    async def scenario():
        starts = []

        class Supervisor(EngineSupervisor):
            async def stop(self):
                if failure == "timeout":
                    await asyncio.Event().wait()
                raise EngineError("controller unavailable")

            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True

            async def register(_):
                pass

            runner._register = register
            with pytest.raises(EngineError, match="confirm engine stop"):
                await asyncio.wait_for(runner.switch("stub-h3", force=True), 0.5)
            assert not starts
            assert runner.needs_reset and not runner.available
            assert not runner.switching and runner.recovery is None
            assert runner.spec.id == DEFAULT
            with pytest.raises(Busy):
                await runner.acquire_gpu()

    monkeypatch.setattr(service, "FORCE_STOP_TIMEOUT_S", 0.01)
    asyncio.run(scenario())


def test_force_switch_cancels_the_job_and_waits_for_confirmed_engine_stop():
    async def scenario():
        rendering, stopping, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        starts, cancellations, tasks = [], [], []

        class Supervisor(EngineSupervisor):
            async def stop(self):
                stopping.set()
                await stopped.wait()

            async def start(self, spec, client):
                assert (
                    stopped.is_set()
                ), "replacement cannot start before confirmed stop"
                starts.append(spec.id)
                self.spec = spec

        class Client:
            idle_known = False

            async def run(self, job):
                tasks.append(asyncio.current_task())
                rendering.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancellations.append(True)
                yield b"never"

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = Client()
            runner.available = True

            async def register(_):
                pass

            runner._register = register
            async with TestServer(app.create_public_app(runner)) as public:
                response = await http.post(
                    public.make_url("/generate"), json={"prompt": "test"}
                )
                switching = None
                try:
                    await asyncio.wait_for(rendering.wait(), 1)
                    switching = asyncio.create_task(
                        runner.switch("stub-h3", force=True)
                    )
                    await asyncio.wait_for(stopping.wait(), 1)
                    assert not starts and not runner.available
                    with pytest.raises(Busy):
                        await runner.acquire_gpu()
                    stopped.set()
                    await asyncio.wait_for(switching, 1)
                    assert cancellations == [True]
                    assert starts == ["stub-h3"]
                    assert runner.available and not runner.needs_reset
                    assert not runner.gpu.locked()
                    assert (
                        runner.recovery is None
                    ), "forced switch must own uncertain-job reconciliation"
                finally:
                    response.close()
                    stopped.set()
                    if switching is not None:
                        switching.cancel()
                        with suppress(asyncio.CancelledError, Exception):
                            await switching
                    for task in tasks:
                        task.cancel()
                        with suppress(asyncio.CancelledError, Exception):
                            await task

    asyncio.run(scenario())


@pytest.mark.parametrize("force", [True, False, "true", 1, None])
def test_admin_switch_requires_a_boolean_force_flag(force):
    async def scenario():
        requested = []
        async with aiohttp.ClientSession() as http:
            supervisor = EngineSupervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)

            async def switch(model, *, force=False):
                requested.append((model, force))

            runner.switch = switch
            async with TestServer(app.create_admin_app(runner, "token")) as admin:
                async with http.post(
                    admin.make_url("/admin/model"),
                    json={"model": DEFAULT, "force": force},
                    headers={"Authorization": "Bearer token"},
                ) as response:
                    assert response.status == (200 if type(force) is bool else 400)
            assert requested == ([(DEFAULT, force)] if type(force) is bool else [])

    asyncio.run(scenario())


def test_failed_switch_waits_for_a_realistic_managed_rollback_before_readmission():
    from video_runners.lifecycle.managed import ManagedSupervisor

    async def scenario():
        async with aiohttp.ClientSession() as http:

            class RollingBack(ManagedSupervisor):
                async def start(self, spec, client):
                    raise EngineError("target startup failed")

                async def preferred_model(self, timeout=1800):
                    # Model restoration takes six simulated seconds, inside its
                    # configured startup bound and beyond the old five seconds.
                    if timeout < 6:
                        raise EngineError("controller recovery timed out")
                    return DEFAULT

                async def attach_restored(self, spec, client):
                    self.spec = spec
                    client.spec = spec
                    self.running = True

            supervisor = RollingBack("http://controller:9200", "token", http)
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True
            registrations = []

            async def register(spec):
                registrations.append(spec.id)

            runner._register = register
            with pytest.raises(EngineError, match="target startup failed"):
                await runner.switch("stub-h3")

            assert runner.available and not runner.needs_reset
            assert runner.spec.id == DEFAULT and registrations == [DEFAULT]
            assert not runner.switching and not runner.gpu.locked()

    asyncio.run(scenario())


def test_graceful_switch_waits_until_the_sse_response_is_finished(monkeypatch):
    from aiohttp import web
    from video_runners.runner import http as routes

    async def scenario():
        finishing, may_finish = asyncio.Event(), asyncio.Event()
        starts = []

        class GatedResponse(web.StreamResponse):
            async def write_eof(self, data=b""):
                finishing.set()
                await may_finish.wait()
                await super().write_eof(data)

        class Client:
            idle_known = True

            async def run(self, job):
                yield b"video"

        class Supervisor(EngineSupervisor):
            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec

        monkeypatch.setattr(routes.web, "StreamResponse", GatedResponse)
        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client, runner.available = Client(), True

            async def register(_):
                pass

            runner._register = register
            async with TestServer(app.create_public_app(runner)) as public:
                response = await http.post(
                    public.make_url("/generate"), json={"prompt": "test"}
                )
                await asyncio.wait_for(finishing.wait(), 1)
                changing = asyncio.create_task(runner.switch("stub-h3"))
                try:
                    for _ in range(3):
                        await asyncio.sleep(0)
                    assert (
                        not starts
                    ), "switching must not truncate the final SSE response"
                finally:
                    may_finish.set()
                    await asyncio.wait_for(changing, 1)
                    payload = await response.text()
                    response.close()
                assert "event: done" in payload
                assert starts == ["stub-h3"]

    asyncio.run(scenario())


def test_graceful_switch_waits_for_the_nodes_single_shot_delivery_release():
    async def scenario():
        starts, closed = [], []

        class Registration:
            active_session_ids = ("delivering-response",)

            async def close(self):
                closed.append(True)

        class Supervisor(EngineSupervisor):
            async def start(self, spec, client):
                starts.append(spec.id)
                self.spec = spec

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(switch_drain_timeout=1),
                MODELS,
                http,
                supervisor=supervisor,
            )
            registration = Registration()
            runner.registrations["single-shot"] = registration
            runner.available = True

            async def register(_):
                pass

            runner._register = register
            changing = asyncio.create_task(runner.switch("stub-h3"))
            try:
                for _ in range(3):
                    await asyncio.sleep(0)
                assert (
                    not closed and not starts
                ), "GPU idle does not establish client delivery completion"
            finally:
                registration.active_session_ids = ()
                await asyncio.wait_for(changing, 1)
            assert closed == [True] and starts == ["stub-h3"]

    asyncio.run(scenario())


def test_delivery_drain_timeout_preserves_registration_and_readmission():
    async def scenario():
        class Registration:
            active_session_ids = ("still-delivering",)

            async def close(self):
                raise AssertionError("registration must remain intact")

        async with aiohttp.ClientSession() as http:
            supervisor = EngineSupervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(switch_drain_timeout=0.01),
                MODELS,
                http,
                supervisor=supervisor,
            )
            registration = Registration()
            runner.registrations["single-shot"] = registration
            runner.available = True
            with pytest.raises(Busy, match="drain timed out"):
                await asyncio.wait_for(runner.switch("stub-h3"), 1)
            assert runner.available and not runner.switching and not runner.gpu.locked()
            assert runner.registrations["single-shot"] is registration
            assert runner.spec.id == DEFAULT and not runner.needs_reset

    asyncio.run(scenario())
