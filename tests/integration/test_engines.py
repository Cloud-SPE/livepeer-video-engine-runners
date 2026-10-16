"""Engine clients and the supervisor, against the CPU stub engine.

Each test starts the packaged stub backend as a child process through EngineSupervisor, the
same way the runner does, on a free port.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import aiohttp
import pytest

from video_runners.backends.base import EngineClient
from video_runners.contracts import EngineError, JobRequest, JobStatus
from video_runners.lifecycle.bundled import EngineSupervisor
from video_runners.backends import engine_client
from video_runners.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[2]
STUB_MODELS, _ = load_catalog(ROOT / "models" / "stub.json")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@asynccontextmanager
async def stub_engine(
    model_id: str, delay: float = 0.2, job_timeout_s: float = 60
) -> AsyncIterator[EngineClient]:
    base = STUB_MODELS[model_id]
    port = _free_port()
    api = "lightx2v" if base.engine == "lightx2v" else "openai"
    spec = replace(
        base,
        command=(sys.executable, "-m", "video_runners.stub_engine", "--api", api)
        + ("--port", str(port), "--delay", str(delay)),
        port=port,
        job_timeout_s=job_timeout_s,
    )
    supervisor = EngineSupervisor()
    async with aiohttp.ClientSession() as http:
        client = engine_client(spec, http)
        await supervisor.start(spec, client)
        try:
            yield client
        finally:
            await supervisor.stop()
    assert not supervisor.running


async def _render(client: EngineClient, job: JobRequest) -> tuple[list[str], bytes]:
    states: list[str] = []
    video = b""
    async for item in client.run(job):
        if isinstance(item, JobStatus):
            states.append(item.state)
        else:
            video = item
    return states, video


@pytest.mark.parametrize("model_id", sorted(STUB_MODELS))
def test_run_returns_an_mp4(model_id: str) -> None:
    async def scenario() -> None:
        async with stub_engine(model_id) as client:
            job = JobRequest.from_payload(
                {"prompt": "a fox", "num_frames": 8}, client.spec.defaults
            )
            states, video = await _render(client, job)
        assert states[-1] == "completed"
        assert video[4:8] == b"ftyp", "not an MP4"

    asyncio.run(scenario())


def test_job_timeout_cancels_the_engine_job() -> None:
    async def scenario() -> None:
        async with stub_engine("stub-wan-t2v", delay=30, job_timeout_s=1.5) as client:
            job = JobRequest.from_payload({"prompt": "slow"}, {})
            with pytest.raises(EngineError, match="exceeded"):
                await _render(client, job)

    asyncio.run(scenario())


def test_abandoned_consumer_cancels_the_engine_job() -> None:
    async def scenario() -> None:
        async with stub_engine("stub-h3", delay=30) as client:
            job_ids: list[str] = []
            submit = client.submit

            async def recording_submit(job: JobRequest) -> str:
                job_ids.append(await submit(job))
                return job_ids[-1]

            client.submit = recording_submit  # type: ignore[method-assign]
            task = asyncio.create_task(
                _render(client, JobRequest.from_payload({"prompt": "x"}, {}))
            )
            await asyncio.sleep(1.5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            status = await client.status(job_ids[0])
        assert status.state == "cancelled"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "prompt is required"),
        ({"prompt": "   "}, "prompt is required"),
        ({"prompt": "x" * 4001}, "at most 4000"),
        ({"prompt": "x", "width": -1}, "non-negative integer"),
        ({"prompt": "x", "steps": True}, "non-negative integer"),
        ({"prompt": "x", "num_frames": "81"}, "non-negative integer"),
    ],
)
def test_job_request_validation(payload: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        JobRequest.from_payload(payload, {})


def test_job_request_applies_defaults_under_payload() -> None:
    job = JobRequest.from_payload(
        {"prompt": " fox ", "width": 320, "steps": None},
        {"width": 832, "height": 480, "steps": 4},
    )
    assert (job.prompt, job.width, job.height, job.steps) == ("fox", 320, 480, 4)
