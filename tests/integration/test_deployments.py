"""Deployment/model contracts, independent of a GPU or Docker daemon."""

import argparse
import asyncio
import json
from pathlib import Path
from string import Template
from dataclasses import replace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from video_runners.controller.policy import Policy
from video_runners.tools.engine_entrypoint import launch_spec
from video_runners.contracts import EngineError, JobRequest
from video_runners.lifecycle.bundled import EngineSupervisor
from video_runners.backends import engine_client
from video_runners.catalog import load_catalog
from video_runners.runner.service import Runner

ROOT = Path(__file__).resolve().parents[2]
ENGINES = ("sglang", "lightx2v", "vllm-omni")
MODELS = [
    (name, spec)
    for name in ENGINES
    for spec in load_catalog(ROOT / f"models/{name}.json")[0].values()
]


@pytest.mark.parametrize("engine,spec", MODELS, ids=[f"{e}/{s.id}" for e, s in MODELS])
def test_managed_and_external_launch_the_same_model(engine, spec):
    command, environment = launch_spec(ROOT / f"models/{engine}.json", spec.id)
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert environment == spec.env
    raw = (ROOT / f"configs/controller/{engine}.json").read_text()
    config = json.loads(
        Template(raw).substitute(
            ENGINE_NAMESPACE="test-owner",
            ENGINE_NETWORK="test-engines",
            ENGINE_GPU_UUID="GPU-reserved-5090",
            HF_CACHE_DIR="/srv/huggingface",
            MODELS_DIR="/srv/weights",
            HF_CACHE_VOLUME="test-hf-cache",
            MODELS_VOLUME="test-model-weights",
            ENGINE_CACHE_VOLUME="test-engine-cache",
            LIGHTX2V_ENGINE_IMAGE="sha256:" + "a" * 64,
        )
    )
    policy = Policy(config)
    assert set(policy.models) == set(load_catalog(ROOT / f"models/{engine}.json")[0])
    assert policy.models[spec.id]["command"] == command
    assert policy.models[spec.id].get("health_path", "/health") == spec.health_path
    gpu = policy.payloads[spec.id]["HostConfig"]["DeviceRequests"]
    assert gpu == [
        {
            "Driver": "nvidia",
            "DeviceIDs": ["GPU-reserved-5090"],
            "Capabilities": [["gpu"]],
        }
    ]


@pytest.mark.parametrize("engine", ENGINES)
def test_external_default_and_unknown_model(engine):
    path = ROOT / f"models/{engine}.json"
    _, default = load_catalog(path)
    assert launch_spec(path) == launch_spec(path, default)
    with pytest.raises(ValueError, match="unknown model"):
        launch_spec(path, "not-a-model")


@pytest.mark.parametrize("engine,spec", MODELS, ids=[f"{e}/{s.id}" for e, s in MODELS])
def test_shipped_models_submit_using_their_engine_contract(engine, spec, monkeypatch):
    async def scenario():
        received = []
        app = web.Application()

        async def submit(request):
            if spec.engine == "openai-videos":
                # SGLang parses multipart or JSON, not URL-encoded forms.
                assert request.content_type == "multipart/form-data"
            body = (
                await request.json()
                if spec.engine == "lightx2v"
                else dict(await request.post())
            )
            received.append(body)
            if spec.engine == "lightx2v":
                assert body["task"] == spec.task
                assert body["size"] == [spec.defaults["height"], spec.defaults["width"]]
                if not spec.supports_negative_prompt:
                    assert "negative_prompt" not in body
                return web.json_response({"task_id": "job"})
            assert body["num_inference_steps"] == str(spec.defaults["steps"])
            assert body["num_frames"] == str(spec.defaults["num_frames"])
            return web.json_response({"id": "job"})

        async def status(_):
            return web.json_response({"status": "completed"})

        async def content(_):
            return web.Response(body=b"\x00\x00\x00\x18ftypmp42")

        base = "/v1/tasks" if spec.engine == "lightx2v" else "/v1/videos"
        app.router.add_post(
            base + ("/video/" if spec.engine == "lightx2v" else ""), submit
        )
        app.router.add_get(
            base + "/job" + ("/status" if spec.engine == "lightx2v" else ""), status
        )
        app.router.add_get(
            base + "/job/" + ("result" if spec.engine == "lightx2v" else "content"),
            content,
        )
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            client = engine_client(
                replace(spec, url=str(server.make_url("/")).rstrip("/")), http
            )
            result = [
                item
                async for item in client.run(
                    JobRequest.from_payload({"prompt": "a fox"}, spec.defaults)
                )
            ]
            assert received[0]["prompt"] == "a fox"
            assert result[-1][4:8] == b"ftyp"
            assert client.idle_known

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["lightx2v", "openai-videos"])
def test_cancellation_failure_is_not_silently_accepted(kind):
    async def scenario():
        app = web.Application()

        async def blocked(_):
            return web.Response(status=409)

        app.router.add_delete("/{path:.*}", blocked)
        spec = next(s for _, s in MODELS if s.engine == kind)
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            client = engine_client(
                replace(spec, url=str(server.make_url("/")).rstrip("/")), http
            )
            with pytest.raises(EngineError, match="cancellation failed"):
                await client.cancel("job")

    asyncio.run(scenario())


def test_h3_negative_prompt_is_rejected_before_admission():
    async def scenario():
        models, _ = load_catalog(ROOT / "models/lightx2v.json")
        supervisor = EngineSupervisor()
        supervisor.spec = models["minimax-h3-4step"]
        async with aiohttp.ClientSession() as http:
            runner = Runner(argparse.Namespace(), models, http, supervisor=supervisor)
            with pytest.raises(ValueError, match="negative prompt"):
                runner.job_request({"prompt": "fox", "negative_prompt": "blur"})

    asyncio.run(scenario())


def test_combined_catalog_preserves_each_engine_configuration():
    public, default = load_catalog(ROOT / "models/all.json")
    trusted = json.loads((ROOT / "configs/controller/all.json").read_text())["models"]
    assert default == "sglang-fastwan2.1-t2v-1.3b"
    assert len(public) == len(trusted) == len(MODELS)
    for engine, source in MODELS:
        name = engine + "-" + source.id
        assert public[name] == replace(source, id=name)
        original = json.loads((ROOT / f"configs/controller/{engine}.json").read_text())
        assert trusted[name] == original["models"][source.id]


def test_failed_submission_leaves_idle_state_unknown():
    async def scenario():
        app = web.Application()

        async def failed(_):
            return web.json_response(
                {"error": "response lost after acceptance"}, status=500
            )

        app.router.add_post("/v1/videos", failed)
        spec = MODELS[0][1]
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            client = engine_client(
                replace(spec, url=str(server.make_url("/")).rstrip("/")), http
            )
            with pytest.raises(EngineError):
                _ = [item async for item in client.run(JobRequest(prompt="fox"))]
            assert not client.idle_known

    asyncio.run(scenario())
