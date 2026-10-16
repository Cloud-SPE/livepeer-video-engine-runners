"""Validation of credential-free engine HTTP origins."""

from __future__ import annotations

from urllib.parse import urlsplit


def engine_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("engine URL must be an HTTP origin without credentials")
    return value.rstrip("/")
