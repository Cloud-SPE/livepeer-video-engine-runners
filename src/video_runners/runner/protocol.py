"""Public application IDs, admission errors and delivery constants."""

from __future__ import annotations


DEFAULT_PORT = 8989
DEFAULT_ADMIN_PORT = 8990
KEEPALIVE_S = 10.0
# SSE carries the MP4 as base64 in events of this many raw bytes.
# Base64 expands a chunk by 4/3; stay below the SDK's 512 KiB line limit.
SSE_CHUNK_BYTES = 256 * 1024
# The orchestrator rejects trickle segments over 10 MB, so stay well below it.
TRICKLE_SEGMENT_BYTES = 8 * 1024 * 1024
# A persistent session writes to each quiet channel at least this often (see
# Session.keep_channels_open); livepeer-node closes channels idle for 5 minutes.
CHANNEL_KEEPALIVE_S = 60.0
# App ids are "<domain>:<capability>/<model>": the capability names the runner
# endpoint family (/generate, /session/*) and the model is the catalog id.
# Clients build the same strings (client.py), so changing them is breaking.
CAPABILITIES = {"single-shot": "video:generations", "persistent": "video:sessions"}


def app_id(mode: str, model_id: str) -> str:
    return f"{CAPABILITIES[mode]}/{model_id}"


class Busy(Exception):
    """The GPU is rendering another job, or the runner is switching models."""
