"""ChannelPublisher against a fake trickle endpoint."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from engines import EngineError
from runner import ChannelPublisher


class FakeChannel:
    """Records segments POSTed to /chan/{seq}; can fail the next few POSTs."""

    def __init__(self) -> None:
        self.segments: dict[int, bytes] = {}
        self.fail_next = 0
        self.deleted = False
        self.app = web.Application()
        self.app.router.add_post("/chan/{seq}", self.post)
        self.app.router.add_delete("/chan", self.delete)

    async def post(self, request: web.Request) -> web.Response:
        if self.fail_next:
            self.fail_next -= 1
            return web.Response(status=500, text="boom")
        self.segments[int(request.match_info["seq"])] = await request.read()
        return web.Response()

    async def delete(self, _request: web.Request) -> web.Response:
        self.deleted = True
        return web.Response()


async def _with_channel(scenario) -> FakeChannel:  # type: ignore[no-untyped-def]
    fake = FakeChannel()
    async with TestServer(fake.app) as server, aiohttp.ClientSession() as http:
        publisher = ChannelPublisher(http, str(server.make_url("/chan/")), "video/mp4")
        await scenario(fake, publisher)
    return fake


def test_segments_are_numbered_from_zero_and_sent_whole() -> None:
    async def scenario(fake: FakeChannel, publisher: ChannelPublisher) -> None:
        await publisher.publish(b"a" * 100_000)
        await publisher.publish(b"")  # keepalive
        await publisher.publish_json({"type": "done"})
        await publisher.close()

    fake = asyncio.run(_with_channel(scenario))
    assert fake.segments[0] == b"a" * 100_000
    assert fake.segments[1] == b""
    assert json.loads(fake.segments[2]) == {"type": "done"}
    assert fake.deleted


def test_one_failure_is_retried_on_the_same_segment() -> None:
    async def scenario(fake: FakeChannel, publisher: ChannelPublisher) -> None:
        fake.fail_next = 1
        await publisher.publish(b"x")
        assert publisher.seq == 1

    assert asyncio.run(_with_channel(scenario)).segments == {0: b"x"}


def test_two_failures_raise_without_advancing() -> None:
    async def scenario(fake: FakeChannel, publisher: ChannelPublisher) -> None:
        fake.fail_next = 2
        with pytest.raises(EngineError, match="HTTP 500"):
            await publisher.publish(b"x")
        assert publisher.seq == 0
        await publisher.publish(b"y")

    assert asyncio.run(_with_channel(scenario)).segments == {0: b"y"}
