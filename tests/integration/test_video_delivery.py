"""Large MP4 transport through the pinned Livepeer SDK's SSE reader."""

import asyncio
import base64
import json
import argparse

from aiohttp import web
from aiohttp.test_utils import TestServer
from livepeer_gateway.live_runner import call_runner

from video_runners.runner.delivery import _send_video
from video_runners.runner.delivery import _sse
from video_runners.client import single_shot


def test_large_video_fits_sdk_sse_line_limit():
    async def scenario():
        video = bytes(range(256)) * 4096
        app = web.Application()

        async def generate(request):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await _send_video(response, video)
            return response

        app.router.add_post("/generate", generate)
        async with TestServer(app) as server:
            stream = await call_runner(str(server.make_url("/generate")), stream=True)
            chunks = []
            event = ""
            async with stream:
                async for line in stream.aiter_lines():
                    if line.startswith("event: "):
                        event = line.removeprefix("event: ")
                    elif event == "video" and line.startswith("data: "):
                        data = json.loads(line.removeprefix("data: "))
                        chunks.append(base64.b64decode(data["b64"]))
            assert b"".join(chunks) == video

    asyncio.run(scenario())


def test_sdk_client_returns_the_actual_provider_with_verified_content(tmp_path):
    async def scenario():
        app = web.Application()
        address = ""

        async def discovery(request):
            return web.json_response(
                [
                    {
                        "address": address,
                        "runners": [
                            {
                                "url": address + "/runner",
                                "app": "video:generations/sample",
                                "runner_id": "runner-test",
                            }
                        ],
                    }
                ]
            )

        async def generate(request):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await _sse(response, "accepted", {"model": "sample"})
            await _send_video(response, b"video payload")
            await _sse(response, "done", {})
            return response

        app.router.add_get("/discovery", discovery)
        app.router.add_post("/runner/generate", generate)
        async with TestServer(app) as server:
            address = str(server.make_url("")).rstrip("/")
            args = argparse.Namespace(
                prompt="A fox",
                width=None,
                height=None,
                num_frames=None,
                steps=None,
                seed=42,
                discovery=address + "/discovery",
                model="sample",
                output=str(tmp_path / "clip"),
            )
            result = await single_shot(args, None)
            assert result is not None
            assert result["runner_url"] == address + "/runner"
            assert result["accepted_model"] == "sample"
            assert (tmp_path / "clip.mp4").read_bytes() == b"video payload"

    asyncio.run(scenario())
