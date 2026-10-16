"""The sampling controls sent over HTTP must survive request parsing."""

import asyncio

import aiohttp
from aiohttp import web
import pytest

from video_runners.backends.openai import OpenAIVideosClient
from video_runners.catalog import ModelSpec
from video_runners.contracts import JobRequest
from video_runners.contracts import EngineError
from video_runners.backends.lightx2v import LightX2VClient
from video_runners import client


def test_openai_adapter_forwards_quality_controls():
    async def scenario():
        received = {}

        async def submit(request):
            async for field in await request.multipart():
                received[field.name] = await field.text()
            return web.json_response({"id": "job-1"})

        app = web.Application()
        app.router.add_post("/v1/videos", submit)
        server = web.AppRunner(app)
        await server.setup()
        site = web.TCPSite(server, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as http:
                client = OpenAIVideosClient(
                    ModelSpec("wan", "openai-videos", (), port), http
                )
                await client.submit(
                    JobRequest.from_payload(
                        {
                            "prompt": "A fox",
                            "guidance_scale": 5,
                            "guidance_scale_2": 4.5,
                            "flow_shift": 8,
                        },
                        {},
                    )
                )
            assert received.get("guidance_scale") == "5.0"
            assert received.get("guidance_scale_2") == "4.5"
            assert received.get("flow_shift") == "8.0"
        finally:
            await server.cleanup()

    asyncio.run(scenario())


def test_client_cli_carries_sampling_controls_into_job_payload(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "video-client",
            "--prompt",
            "A fox",
            "--fps",
            "24",
            "--negative-prompt",
            "flicker",
            "--guidance-scale",
            "5",
            "--guidance-scale-2",
            "4",
            "--flow-shift",
            "8",
        ],
    )
    payload = client._job_payload(client._parse_args())
    assert {
        key: payload.get(key)
        for key in (
            "fps",
            "negative_prompt",
            "guidance_scale",
            "guidance_scale_2",
            "flow_shift",
        )
    } == {
        "fps": 24,
        "negative_prompt": "flicker",
        "guidance_scale": 5.0,
        "guidance_scale_2": 4.0,
        "flow_shift": 8.0,
    }


def test_lightx2v_refuses_request_time_sampling_controls_before_http():
    async def scenario():
        client = LightX2VClient(ModelSpec("wan", "lightx2v", (), 9100), None)
        with pytest.raises(EngineError, match="engine configuration"):
            await client.submit(JobRequest(prompt="A fox", guidance_scale=5))

    asyncio.run(scenario())
