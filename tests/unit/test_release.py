"""Portable, credential-free release manifests and digest-only deployment inputs."""

import json
from pathlib import Path
import pytest

from video_runners.tools import release

ROOT = Path(__file__).resolve().parents[2]


def test_release_plan_separates_cpu_roles_from_gpu_engine_and_pins_node_source():
    plan = release.plan(ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40)
    assert set(plan["components"]) == {
        "runner",
        "controller",
        "node",
        "model-tools",
        "lightx2v-engine",
    }
    for name in ("runner", "controller", "model-tools"):
        assert plan["components"][name]["target"] == name
        assert plan["components"][name]["dockerfile"] == "deploy/docker/cpu.Dockerfile"
    assert (
        plan["components"]["runner"]["tag"]
        == "registry.example.com/operator/livepeer-video-runner:v0.3.0"
    )
    assert (
        plan["components"]["node"]["context"]
        == "https://github.com/livepeer/node.git#08081dbda0f4f7b56e362e3af4b6965bfa1b73a4"
    )
    assert plan["engine_inputs"] == json.loads(
        (ROOT / "configs/engine-images.json").read_text()
    )
    assert plan["source_revision"] == "a" * 40


@pytest.mark.parametrize(
    "field,value",
    [
        ("registry", "https://registry.example.com"),
        ("registry", "user:password@registry.example.com"),
        ("namespace", "../other"),
        ("tag", "latest"),
        ("tag", "bad\nvalue"),
        ("revision", "main"),
    ],
)
def test_release_inputs_reject_credentials_paths_and_mutable_aliases(field, value):
    arguments = dict(
        registry="registry.example.com",
        namespace="operator",
        tag="v0.3.0",
        revision="a" * 40,
    )
    arguments[field] = value
    with pytest.raises(ValueError):
        release.plan(ROOT, **arguments)


def test_publish_records_registry_digests_and_exports_reusable_compose_inputs(tmp_path):
    planned = release.plan(ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40)
    calls = []

    def docker(*args, capture=False):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            tag = args[-1]
            return json.dumps([tag.rsplit(":", 1)[0] + "@sha256:" + "b" * 64])
        return ""

    output = tmp_path / "release"
    release.publish(ROOT, planned, output, docker)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "published"
    assert set(manifest["images"]) == set(planned["components"])
    assert all(
        value.endswith("@sha256:" + "b" * 64) for value in manifest["images"].values()
    )
    env = (output / "release.env").read_text()
    assert (
        "RUNNER_IMAGE=registry.example.com/operator/livepeer-video-runner@sha256:"
        + "b" * 64
        in env
    )
    assert (
        "LIGHTX2V_ENGINE_IMAGE=registry.example.com/operator/livepeer-video-lightx2v-engine@sha256:"
        + "b" * 64
        in env
    )
    assert "SGLANG_ENGINE_IMAGE=" + planned["engine_inputs"]["sglang"] in env
    assert len([call for call in calls if call[0] == "push"]) == 5
    assert not any("login" in call for call in calls)


@pytest.mark.parametrize(
    "image",
    [
        "registry.example.com/operator/runner:latest",
        "https://user:secret@registry.example.com/operator/runner@sha256:" + "c" * 64,
        "sha256:" + "c" * 64,
    ],
)
def test_deployment_inputs_refuse_mutable_or_credential_bearing_image_references(image):
    planned = release.plan(ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40)
    manifest = {
        **planned,
        "images": {
            name: value["tag"].rsplit(":", 1)[0] + "@sha256:" + "b" * 64
            for name, value in planned["components"].items()
        },
    }
    manifest["images"]["runner"] = image
    with pytest.raises(ValueError, match="digest"):
        release.deployment_env(manifest)


def test_pull_refuses_an_incomplete_release_before_contacting_docker(tmp_path):
    planned = release.plan(ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40)
    calls = []
    with pytest.raises(ValueError, match="published"):
        release.pull(
            ROOT,
            {**planned, "status": "failed", "images": {}},
            tmp_path / "release.env",
            lambda *args, **kwargs: calls.append(args),
        )
    assert not calls and not (tmp_path / "release.env").exists()


def test_pull_stages_exact_digests_and_preserves_existing_env_files(tmp_path):
    planned = release.plan(ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40)
    manifest = {
        **planned,
        "status": "published",
        "images": {
            name: value["tag"].rsplit(":", 1)[0] + "@sha256:" + "b" * 64
            for name, value in planned["components"].items()
        },
    }
    calls = []
    destination = tmp_path / "selected.env"
    release.pull(
        ROOT, manifest, destination, lambda *args, **kwargs: calls.append(args)
    )
    assert len(calls) == 7 and all(
        call[0] == "pull" and "@sha256:" in call[1] for call in calls
    )
    assert destination.read_text() == release.deployment_env(manifest)
    original = destination.read_bytes()
    calls.clear()
    with pytest.raises(ValueError, match="existing env"):
        release.pull(
            ROOT, manifest, destination, lambda *args, **kwargs: calls.append(args)
        )
    assert not calls and destination.read_bytes() == original
