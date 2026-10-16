"""Large MP4 transport through the pinned Livepeer SDK's SSE reader."""

import asyncio
import base64
import json

from aiohttp import web
from aiohttp.test_utils import TestServer
from livepeer_gateway.live_runner import call_runner

from video_runners.runner.delivery import _send_video


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
