"""Restricted Docker API transport; daemon bodies never escape on errors."""

from __future__ import annotations

import re
from typing import Any
import aiohttp
from video_runners.contracts import EngineError
from video_runners.origins import engine_url


class Docker:
    def __init__(self, url: str, http: aiohttp.ClientSession) -> None:
        self.url = engine_url(url) + "/v1.51"
        self.http = http

    async def call(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        async with self.http.request(
            method,
            self.url + path,
            json=body,
            params=params,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as response:
            if response.status == 404:
                if method == "DELETE" or (
                    method == "GET"
                    and re.fullmatch(r"/containers/[a-f0-9]{64}/json", path)
                ):
                    return None
                raise EngineError(
                    "Docker resource unavailable; pre-pull the configured image"
                )
            if response.status >= 400:
                # Do not return daemon bodies, which may contain host configuration.
                raise EngineError(f"Docker API returned HTTP {response.status}")
            if response.status in {204, 304}:
                return {}
            return await response.json()
