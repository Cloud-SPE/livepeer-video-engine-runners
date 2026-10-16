"""Every shipped catalog loads, and catalog validation rejects bad entries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_runners.catalog import load_catalog
from video_runners.runner.protocol import CAPABILITIES, app_id

ROOT = Path(__file__).resolve().parents[2]
CATALOGS = sorted((ROOT / "models").glob("*.json"))


def test_every_engine_has_a_catalog_and_dockerfile() -> None:
    names = {path.stem for path in CATALOGS}
    assert names == {"stub", "lightx2v", "sglang", "vllm-omni", "all"}
    # The combined catalog switches between separate images in managed mode.
    for name in names - {"all"}:
        assert (ROOT / "deploy/docker" / f"{name}.Dockerfile").is_file()


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.stem)
def test_catalog_loads(path: Path) -> None:
    models, default = load_catalog(path)
    assert default in models
    for spec in models.values():
        # The engine must listen where the runner looks for it.
        assert str(spec.port) in spec.command
        assert spec.job_timeout_s > 0 and spec.startup_timeout_s > 0
        for config in (arg for arg in spec.command if arg.startswith("/app/configs/")):
            assert (ROOT / config.removeprefix("/app/")).is_file(), config


def test_app_ids() -> None:
    assert app_id("single-shot", "wan2.1-t2v-1.3b") == (
        "video:generations/wan2.1-t2v-1.3b"
    )
    assert app_id("persistent", "wan2.1-t2v-1.3b") == "video:sessions/wan2.1-t2v-1.3b"
    assert set(CAPABILITIES) == {"single-shot", "persistent"}


def _write(tmp_path: Path, catalog: dict) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    return path


def _entry(**overrides: object) -> dict:
    return {
        "id": "m",
        "engine": "openai-videos",
        "command": ["x"],
        "port": 1,
        **overrides,
    }


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        ({"models": [_entry(id="Bad/Id")]}, "must be lowercase"),
        ({"models": [_entry(engine="comfy")]}, "engine must be one of"),
        ({"models": [_entry(), _entry()]}, "duplicate model id"),
        ({"default": "nope", "models": [_entry()]}, "not in the catalog"),
    ],
)
def test_catalog_rejects(tmp_path: Path, catalog: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_catalog(_write(tmp_path, catalog))


def test_default_falls_back_to_first_model(tmp_path: Path) -> None:
    _, default = load_catalog(_write(tmp_path, {"models": [_entry(id="first")]}))
    assert default == "first"
