"""Private Prometheus exposition and actual request outcome accounting."""

import argparse
import asyncio
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from prometheus_client.parser import text_string_to_metric_families
from prometheus_client import generate_latest

from video_runners.catalog import load_catalog
from video_runners.lifecycle.bundled import EngineSupervisor
from video_runners.runner import app
from video_runners.runner.service import Runner
from video_runners.contracts import EngineError
from video_runners.backends import engine_client

MODELS, DEFAULT = load_catalog(Path(__file__).resolve().parents[2] / "models/stub.json")


def test_metrics_require_admin_auth_and_are_absent_from_the_public_listener():
    async def scenario():
        async with aiohttp.ClientSession() as http:
            supervisor = EngineSupervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            async with TestServer(
                app.create_admin_app(runner, "private-token")
            ) as admin:
                url = admin.make_url("/metrics")
                async with http.get(url) as response:
                    assert response.status == 401
                async with http.get(
                    url, headers={"Authorization": "Bearer wrong"}
                ) as response:
                    assert response.status == 401
                async with http.get(
                    url, headers={"Authorization": "Bearer private-token"}
                ) as response:
                    assert response.status == 200
                    assert "video_runner_gpu_busy 0.0" in await response.text()
                await runner.gpu.acquire()
                async with http.get(
                    url, headers={"Authorization": "Bearer private-token"}
                ) as response:
                    assert "video_runner_gpu_busy 1.0" in await response.text()
                runner.gpu.release()
            async with TestServer(app.create_public_app(runner)) as public:
                async with http.get(public.make_url("/metrics")) as response:
                    assert response.status == 404

    asyncio.run(scenario())


@pytest.mark.parametrize("fails", [False, True])
def test_owned_engine_recovery_records_success_or_failure(fails):
    async def scenario():
        class Supervisor(EngineSupervisor):
            async def start(self, spec, client):
                if fails:
                    raise EngineError("engine cannot restart")
                self.spec = spec

        async with aiohttp.ClientSession() as http:
            supervisor = Supervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(argparse.Namespace(), MODELS, http, supervisor=supervisor)
            runner.client = engine_client(supervisor.spec, http)
            runner.needs_reset = True

            async def register(_):
                pass

            runner._register = register
            await runner.recover_uncertain_job(runner.client)
            outcome = "failed" if fails else "succeeded"
            text = generate_latest(runner.metrics.registry).decode()
            assert (
                f'video_runner_engine_restarts_total{{model="{DEFAULT}",outcome="{outcome}"}} 1.0'
                in text
            )
            assert runner.needs_reset is fails

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_persistent_jobs_record_their_terminal_outcome_once(outcome):
    async def scenario():
        began = asyncio.Event()

        class Client:
            idle_known = True

            async def run(self, job):
                began.set()
                if outcome == "cancelled":
                    await asyncio.Event().wait()
                if outcome == "failed":
                    raise EngineError("engine failure")
                yield b"video"

        class Channel:
            async def publish_json(self, body):
                pass

            async def publish(self, body):
                pass

        async with aiohttp.ClientSession() as http:
            supervisor = EngineSupervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = Client()
            runner.available = True
            session = SimpleNamespace(
                job=None, idle_since=0, events=Channel(), video=Channel()
            )
            runner.sessions["session"] = session
            async with (
                TestServer(app.create_public_app(runner)) as public,
                TestServer(app.create_admin_app(runner, "token")) as admin,
            ):
                async with http.post(
                    public.make_url("/session/jobs"),
                    json={"prompt": "test"},
                    headers={"Livepeer-Session-Id": "session"},
                ) as response:
                    assert response.status == 202
                await asyncio.wait_for(began.wait(), 1)
                if outcome == "cancelled":
                    session.job.cancel()
                with suppress(asyncio.CancelledError):
                    await asyncio.wait_for(session.job, 1)
                async with http.get(
                    admin.make_url("/metrics"),
                    headers={"Authorization": "Bearer token"},
                ) as response:
                    samples = [
                        sample
                        for family in text_string_to_metric_families(
                            await response.text()
                        )
                        for sample in family.samples
                    ]
                totals = [
                    sample
                    for sample in samples
                    if sample.name == "video_runner_jobs_total"
                ]
                assert [(sample.labels, sample.value) for sample in totals] == [
                    (
                        {
                            "model": DEFAULT,
                            "delivery": "persistent",
                            "outcome": outcome,
                        },
                        1,
                    )
                ]
                assert not runner.gpu.locked()

    asyncio.run(scenario())


def test_busy_refusals_are_counted_without_being_counted_as_finished_jobs():
    async def scenario():
        async with aiohttp.ClientSession() as http:
            supervisor = EngineSupervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = engine_client(supervisor.spec, http)
            runner.available = True
            await runner.gpu.acquire()
            try:
                async with (
                    TestServer(app.create_public_app(runner)) as public,
                    TestServer(app.create_admin_app(runner, "token")) as admin,
                ):
                    async with http.post(
                        public.make_url("/generate"), json={"prompt": "test"}
                    ) as response:
                        assert response.status == 503
                    async with http.get(
                        admin.make_url("/metrics"),
                        headers={"Authorization": "Bearer token"},
                    ) as response:
                        text = await response.text()
                    samples = [
                        sample
                        for family in text_string_to_metric_families(text)
                        for sample in family.samples
                    ]
                    totals = [
                        sample
                        for sample in samples
                        if sample.name == "video_runner_refusals_total"
                    ]
                    assert [(sample.labels, sample.value) for sample in totals] == [
                        ({"model": DEFAULT, "reason": "busy"}, 1)
                    ]
                    assert not any(
                        sample.name == "video_runner_jobs_total" for sample in samples
                    )
            finally:
                runner.gpu.release()

    asyncio.run(scenario())


def test_requests_during_initial_engine_loading_are_refused_cleanly():
    async def scenario():
        async with aiohttp.ClientSession() as http:
            runner = Runner(argparse.Namespace(busy="reject"), MODELS, http)
            async with TestServer(app.create_public_app(runner)) as public:
                async with http.post(
                    public.make_url("/generate"), json={"prompt": "test"}
                ) as response:
                    assert response.status == 503

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_metrics_count_real_single_shot_outcomes_without_recording_prompts(outcome):
    async def scenario():
        class Client:
            idle_known = True

            async def run(self, job):
                if outcome == "failed":
                    raise EngineError("test engine failure")
                yield b"delivered-video"

        async with aiohttp.ClientSession() as http:
            supervisor = EngineSupervisor()
            supervisor.spec = MODELS[DEFAULT]
            runner = Runner(
                argparse.Namespace(busy="reject"), MODELS, http, supervisor=supervisor
            )
            runner.client = Client()
            runner.available = True
            async with (
                TestServer(app.create_public_app(runner)) as public,
                TestServer(app.create_admin_app(runner, "token")) as admin,
            ):
                async with http.post(
                    public.make_url("/generate"),
                    json={"prompt": "private subject never in metrics"},
                ) as response:
                    assert response.status == 200
                    body = await response.text()
                    assert (
                        f"event: {'done' if outcome == 'completed' else 'error'}"
                        in body
                    )
                async with http.get(
                    admin.make_url("/metrics"),
                    headers={"Authorization": "Bearer token"},
                ) as response:
                    text = await response.text()
                samples = [
                    sample
                    for family in text_string_to_metric_families(text)
                    for sample in family.samples
                ]
                totals = [
                    sample
                    for sample in samples
                    if sample.name == "video_runner_jobs_total"
                ]
                assert [(sample.labels, sample.value) for sample in totals] == [
                    (
                        {
                            "model": DEFAULT,
                            "delivery": "single-shot",
                            "outcome": outcome,
                        },
                        1,
                    )
                ]
                durations = [
                    sample
                    for sample in samples
                    if sample.name == "video_runner_job_duration_seconds_count"
                ]
                assert len(durations) == 1 and durations[0].value == 1
                assert not runner.gpu.locked()
                assert "private subject" not in text
                assert "test engine failure" not in text

    asyncio.run(scenario())
