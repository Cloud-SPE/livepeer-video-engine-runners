"""Engine-independent generation requests, status and errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class EngineError(RuntimeError):
    """The engine rejected a job, failed it, or is not running."""


@dataclass
class JobRequest:
    """A generation request after the catalog defaults are applied."""

    prompt: str
    negative_prompt: str = ""
    width: int | None = None
    height: int | None = None
    num_frames: int | None = None
    fps: int | None = None
    steps: int | None = None
    seed: int | None = None

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], defaults: dict[str, Any]
    ) -> JobRequest:
        merged = {**defaults, **{k: v for k, v in payload.items() if v is not None}}
        prompt = merged.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        if len(prompt) > 4000:
            raise ValueError("prompt must be at most 4000 characters")

        def _int(name: str) -> int | None:
            value = merged.get(name)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            return value

        return cls(
            prompt=prompt.strip(),
            negative_prompt=str(merged.get("negative_prompt", "")),
            width=_int("width"),
            height=_int("height"),
            num_frames=_int("num_frames"),
            fps=_int("fps"),
            steps=_int("steps"),
            seed=_int("seed"),
        )


@dataclass(frozen=True)
class JobStatus:
    state: str  # queued | running | completed | failed | cancelled
    progress: int | None = None
    error: str = ""
