"""Persistent session channels, idle expiry and cleanup."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
import aiohttp
from video_runners.contracts import EngineError
from video_runners.runner.delivery import ChannelPublisher
from video_runners.runner.protocol import CHANNEL_KEEPALIVE_S

log = logging.getLogger("video-runner")


@dataclass
class Session:
    """A persistent session's channels and its in-flight job."""

    session_id: str
    video_url: str
    events_url: str
    video: ChannelPublisher
    events: ChannelPublisher
    # The orchestrator's per-session callback URL and credential, for stop().
    control_url: str
    token: str
    job: asyncio.Task[None] | None = None
    idle_since: float = field(default_factory=time.monotonic)
    reaper: asyncio.Task[None] | None = None
    keepalive: asyncio.Task[None] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "session": self.session_id,
            "video": self.video_url,
            "events": self.events_url,
        }

    @property
    def busy(self) -> bool:
        return self.job is not None and not self.job.done()

    async def stop(self, http: aiohttp.ClientSession) -> None:
        """Ask the orchestrator to release this session (as if the client had)."""
        async with http.post(
            self.control_url + "/stop", headers={"Livepeer-Session-Token": self.token}
        ) as resp:
            if resp.status >= 400:
                log.warning(
                    "stop %s: HTTP %d %s",
                    self.session_id,
                    resp.status,
                    await resp.text(),
                )

    async def reap_when_idle(
        self, http: aiohttp.ClientSession, timeout_s: float
    ) -> None:
        """Release a session that holds the runner without rendering anything.

        Off-chain sessions never expire on their own, so a client that dies
        without releasing would otherwise keep this runner's capacity forever.
        """
        while True:
            await asyncio.sleep(min(15.0, timeout_s))
            if not self.busy and time.monotonic() - self.idle_since > timeout_s:
                log.info(
                    "session %s idle for %gs; releasing", self.session_id, timeout_s
                )
                await self.stop(http)
                return

    async def keep_channels_open(self) -> None:
        """Write an empty segment to each channel that has been quiet a while.

        livepeer-node closes a trickle channel after five minutes without a
        write, and a GPU render can take longer than that. Clients skip empty
        segments.
        """
        while True:
            await asyncio.sleep(CHANNEL_KEEPALIVE_S / 2)
            for channel in (self.video, self.events):
                if time.monotonic() - channel.last_write >= CHANNEL_KEEPALIVE_S:
                    try:
                        await channel.publish(b"")
                    except EngineError as exc:
                        log.warning("session %s keepalive: %s", self.session_id, exc)

    async def close(self) -> None:
        for task in (self.reaper, self.keepalive):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        if self.job is not None and not self.job.done():
            self.job.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.job
        with suppress(Exception):
            await self.events.close()
        with suppress(Exception):
            await self.video.close()
