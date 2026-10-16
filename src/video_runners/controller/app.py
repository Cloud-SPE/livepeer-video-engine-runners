"""Private, single-GPU Docker lifecycle controller. No Livepeer dependencies."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from video_runners.controller.http import serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=Path("/state"))
    parser.add_argument("--lease-dir", type=Path, default=Path("/leases"))
    parser.add_argument(
        "--docker-url",
        default=os.environ.get("DOCKER_HOST", "http://socket-proxy:2375").replace(
            "tcp://", "http://"
        ),
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9200)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(parser.parse_args()))
