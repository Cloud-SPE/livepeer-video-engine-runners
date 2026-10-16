"""Public model definitions and catalog parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENGINE_KINDS = frozenset({"lightx2v", "openai-videos"})
MODEL_ID = re.compile(r"[a-z0-9][a-z0-9.-]*")


@dataclass(frozen=True)
class ModelSpec:
    """One catalog entry: which engine to run, with what, for which model.

    `id` names the model, not the engine: the runner advertises it in its app
    ids, so the same model served by two engines is one offering on the network.
    """

    id: str
    engine: str
    command: tuple[str, ...]
    port: int
    health_path: str = "/health"
    startup_timeout_s: float = 1800.0
    job_timeout_s: float = 1800.0
    price_usd_per_hour: float = 0.0
    env: dict[str, str] = field(default_factory=dict)
    # Request fields used when the client leaves them out. Each engine reads only
    # the ones its API supports (LightX2V takes step count from its startup config).
    defaults: dict[str, Any] = field(default_factory=dict)
    # openai-videos only: the `model` form field, when the server wants one.
    served_model: str = ""
    # LightX2V variants may serve several tasks from one loaded transformer.
    task: str = ""
    supports_negative_prompt: bool = True
    url: str = ""

    @property
    def base_url(self) -> str:
        return self.url or f"http://127.0.0.1:{self.port}"


def load_catalog(path: Path) -> tuple[dict[str, ModelSpec], str]:
    """Read models.json: {"default": id, "models": [ModelSpec fields...]}."""
    raw = json.loads(path.read_text())
    models: dict[str, ModelSpec] = {}
    for entry in raw["models"]:
        spec = ModelSpec(
            id=entry["id"],
            engine=entry["engine"],
            command=tuple(entry["command"]),
            port=int(entry["port"]),
            health_path=entry.get("health_path", "/health"),
            startup_timeout_s=float(entry.get("startup_timeout_s", 1800)),
            job_timeout_s=float(entry.get("job_timeout_s", 1800)),
            price_usd_per_hour=float(entry.get("price_usd_per_hour", 0)),
            env={k: str(v) for k, v in entry.get("env", {}).items()},
            defaults=dict(entry.get("defaults", {})),
            served_model=entry.get("served_model", ""),
            task=entry.get("task", ""),
            supports_negative_prompt=entry.get("supports_negative_prompt", True),
        )
        if not MODEL_ID.fullmatch(spec.id):
            raise ValueError(
                f"model id {spec.id!r} must be lowercase letters, digits, '.', '-'"
            )
        if spec.engine not in ENGINE_KINDS:
            raise ValueError(f"{spec.id}: engine must be one of {sorted(ENGINE_KINDS)}")
        if spec.id in models:
            raise ValueError(f"duplicate model id {spec.id!r}")
        models[spec.id] = spec
    default = raw.get("default") or next(iter(models))
    if default not in models:
        raise ValueError(f"default model {default!r} is not in the catalog")
    return models, default
