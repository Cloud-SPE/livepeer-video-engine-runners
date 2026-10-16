"""Select the engine HTTP adapter from a public model definition."""

from __future__ import annotations

import aiohttp
from video_runners.catalog import ModelSpec
from video_runners.backends.base import EngineClient
from video_runners.backends.lightx2v import LightX2VClient
from video_runners.backends.openai import OpenAIVideosClient


def engine_client(spec: ModelSpec, session: aiohttp.ClientSession) -> EngineClient:
    if spec.engine == "lightx2v":
        return LightX2VClient(spec, session)
    return OpenAIVideosClient(spec, session)
