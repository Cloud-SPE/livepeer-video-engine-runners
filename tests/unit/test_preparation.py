"""Operator-facing initialization and pinned asset plans."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from video_runners.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[2]


def initializer():
    spec = importlib.util.spec_from_file_location(
        "deployment_init", ROOT / "src/video_runners/tools/init_deployment.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "mode,engine",
    [
        ("managed", "all"),
        ("external", "sglang"),
        ("external", "vllm-omni"),
        ("external", "lightx2v"),
    ],
)
def test_initialization_preserves_private_settings_and_creates_external_volumes(
    tmp_path, monkeypatch, existing, mode, engine
):
    module = initializer()
    destination = tmp_path / ".env"
    calls = []

    def output(*command):
        if command[:3] == ("docker", "compose", "version"):
            return "5.6.0"
        if command[:2] == ("docker", "version"):
            return json.dumps({"MinAPIVersion": "1.44", "ApiVersion": "1.56"})
        if command[:3] == ("docker", "network", "ls"):
            return "existing-network"
        if command[:3] == ("docker", "network", "inspect"):
            return json.dumps([{"IPAM": {"Config": [{"Subnet": "172.30.0.0/16"}]}}])
        if command[0] == "nvidia-smi":
            return "GPU-reserved-5090"
        return "[]"

    monkeypatch.setattr(module, "output", output)
    monkeypatch.setattr(module.subprocess, "run", lambda args, **kw: calls.append(args))
    arguments = ["init", "--env-file", str(destination), "--project", "operator-video"]
    arguments += ["--mode", mode, "--engine", engine]
    if existing:
        arguments.append("--existing-orchestrator")
    monkeypatch.setattr(sys, "argv", arguments)
    module.main()
    values = dict(
        line.split("=", 1)
        for line in destination.read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert destination.stat().st_mode & 0o777 == 0o600
    assert values["ENGINE_GPU_UUID"] == "GPU-reserved-5090"
    assert values["GPU_ID"] == "GPU-reserved-5090"
    assert not values["SUBNET_PREFIX"].startswith("172.30.")
    assert values["USE_EXISTING_ORCHESTRATOR"] == str(int(existing))
    assert bool(values["BOOTSTRAP_SECRET"]) is not existing
    assert len(values["ENGINE_CONTROLLER_TOKEN"]) == 64
    assert values["RUNNER_ADMIN_TOKEN"] != values["ENGINE_CONTROLLER_TOKEN"]
    expected = {
        "livepeer-video-hf-cache",
        "livepeer-video-model-weights",
        "livepeer-video-engine-cache",
    }
    if mode == "managed":
        expected |= {"operator-video-controller-state", "livepeer-video-gpu-leases"}
    else:
        images = json.loads((ROOT / "configs/engine-images.json").read_text())
        assert values["EXTERNAL_ENGINE_IMAGE"] == (
            "livepeer-video-lightx2v-engine:local"
            if engine == "lightx2v"
            else images[engine]
        )
    assert {call[-1] for call in calls} == expected
    saved = destination.read_bytes()
    calls.clear()
    with pytest.raises(SystemExit):
        module.main()
    assert destination.read_bytes() == saved
    assert not calls


def test_every_model_has_an_immutable_weight_plan():
    manifest = json.loads((ROOT / "configs/model-assets.json").read_text())
    for engine, entries in manifest["models"].items():
        models, default = load_catalog(ROOT / f"models/{engine}.json")
        assert set(entries) == set(models)
        assert manifest["defaults"][engine] == default
        for spec in entries.values():
            for asset in [spec, *spec.get("extra_files", [])]:
                assert re.fullmatch(r"[0-9a-f]{40}", asset["revision"])
            assert spec["storage"] in {"hf", "models"}
