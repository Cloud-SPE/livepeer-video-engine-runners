"""Literal private configuration and durable image-preparation progress."""

import json
import sys

import pytest

from video_runners.tools.operator_io import read_env
from video_runners.tools import prepare_engines


def test_env_values_are_literal_and_later_files_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    private = tmp_path / "settings.env"
    private.write_text(
        "# Generated settings\n\nTOKEN='a=b'\nEMPTY=\nPORT = 8990\n"
        'UNEXPANDED=$(touch should-not-exist)\nQUOTED="$HOME"\n'
    )
    staged = tmp_path / "images.env"
    staged.write_text("PORT=9000\nIMAGE=sha256:abc\n")
    assert read_env(private, tmp_path / "missing", staged) == {
        "TOKEN": "a=b",
        "EMPTY": "",
        "PORT": "9000",
        "UNEXPANDED": "$(touch should-not-exist)",
        "QUOTED": "$HOME",
        "IMAGE": "sha256:abc",
    }
    assert not (tmp_path / "should-not-exist").exists()


def test_image_preparation_preserves_completed_work_on_later_failure(
    tmp_path, monkeypatch
):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/engine-images.json").write_text(json.dumps({}))
    destination = tmp_path / ".engine-images.env"
    destination.write_text("LIGHTX2V_ENGINE_IMAGE=sha256:existing\n")
    monkeypatch.setattr(prepare_engines, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["prepare-engines", "all"])

    def stage(engine, images):
        if engine == "vllm-omni":
            raise RuntimeError("build failed")
        return "sglang@sha256:pinned"

    monkeypatch.setattr(prepare_engines, "stage", stage)
    with pytest.raises(RuntimeError, match="build failed"):
        prepare_engines.main()
    assert read_env(destination) == {
        "LIGHTX2V_ENGINE_IMAGE": "sha256:existing",
        "SGLANG_ENGINE_IMAGE": "sglang@sha256:pinned",
    }
