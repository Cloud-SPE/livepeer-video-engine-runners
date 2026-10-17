"""Portable, credential-free release manifests and digest-only deployment inputs."""

import json
import shutil
from copy import deepcopy
from pathlib import Path
import pytest

from video_runners.tools import release

ROOT = Path(__file__).resolve().parents[2]


def test_application_release_publishes_only_cpu_roles_without_an_engine_baseline(
    tmp_path,
):
    planned = release.plan(ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40)
    calls = []

    def docker(*args, capture=False):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([args[-1].rsplit(":", 1)[0] + "@sha256:" + "b" * 64])
        return ""

    output = tmp_path / "cpu-release"
    release.publish(ROOT, planned, output, docker)
    assert set(planned["components"]) == {"runner", "controller", "model-tools", "node"}
    assert len([call for call in calls if call[0] == "push"]) == 4
    assert not any(
        engine in part.lower()
        for call in calls
        for part in call
        for engine in ("lightx2v", "sglang", "vllm")
    )
    values = dict(
        line.split("=", 1)
        for line in (output / "release.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert set(values) == {
        "RUNNER_IMAGE",
        "CONTROLLER_IMAGE",
        "MODEL_TOOLS_IMAGE",
        "LIVEPEER_NODE_IMAGE",
    }


@pytest.mark.parametrize("action", ["publish", "pull"])
def test_gpu_bundle_is_refused_before_any_docker_action(tmp_path, action):
    manifest = release.plan(
        ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40
    )
    manifest["components"]["lightx2v-engine"] = {
        "tag": "registry.example.com/operator/engine:v0.3.0",
        "context": ".",
        "dockerfile": "deploy/docker/lightx2v-engine.Dockerfile",
    }
    manifest.update(
        status="published",
        images={
            name: value["tag"].rsplit(":", 1)[0] + "@sha256:" + "b" * 64
            for name, value in manifest["components"].items()
        },
    )
    calls = []

    def docker(*args, capture=False):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([args[-1].rsplit(":", 1)[0] + "@sha256:" + "b" * 64])
        return ""

    with pytest.raises(ValueError, match="CPU-only"):
        getattr(release, action)(ROOT, manifest, tmp_path / "output", docker)
    assert not calls
    assert not (tmp_path / "output").exists()


def test_cpu_release_needs_no_operator_engine_build_files(tmp_path):
    files = [
        "pyproject.toml",
        "uv.lock",
        "configs/model-assets.json",
        "compose.prod.yml",
        "compose.dev.yml",
        "deploy/compose/signer.yml",
        "deploy/compose/assets.yml",
        "deploy/docker/cpu.Dockerfile",
    ]
    files += [
        str(p.relative_to(ROOT))
        for folder in ("models", "configs/controller")
        for p in (ROOT / folder).glob("*.json")
    ]
    for name in files:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    planned = release.plan(
        tmp_path, "registry.example.com", "operator", "v0.3.0", "a" * 40
    )
    assert set(planned["components"]) == {"runner", "controller", "model-tools", "node"}


def test_cpu_release_optionally_reuses_only_the_same_source_node_without_rewriting_evidence():
    previous = release.plan(
        ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40
    )
    previous.update(
        status="published",
        images={
            name: component["tag"].rsplit(":", 1)[0] + "@sha256:" + "b" * 64
            for name, component in previous["components"].items()
        },
    )
    original = deepcopy(previous)
    current = release.plan(ROOT, "registry.example.com", "operator", "v0.3.1", "c" * 40)
    release.reuse_images(current, previous)
    assert current["components"]["node"]["reuse"] == previous["images"]["node"]
    assert all(
        "reuse" not in current["components"][name]
        for name in ["runner", "controller", "model-tools"]
    )
    assert current["components"]["node"]["tag"] == previous["components"]["node"]["tag"]
    assert (
        current["components"]["node"]["image_source_revision"]
        == previous["components"]["node"]["context"].rsplit("#", 1)[1]
    )
    assert previous == original


@pytest.mark.parametrize(
    "change", ["incomplete", "schema", "scope", "missing_role", "digest"]
)
def test_node_reuse_refuses_incomplete_or_non_cpu_release_manifests(change):
    current = release.plan(ROOT, "registry.example.com", "operator", "v0.3.1", "c" * 40)
    previous = deepcopy(current)
    previous.update(
        status="published",
        images={
            name: component["tag"].rsplit(":", 1)[0] + "@sha256:" + "b" * 64
            for name, component in previous["components"].items()
        },
    )
    if change == "incomplete":
        previous["status"] = "failed"
    elif change == "schema":
        previous["schema_version"] = 1
    elif change == "scope":
        previous["scope"] = "engines"
    elif change == "missing_role":
        del previous["images"]["controller"]
    else:
        previous["images"]["node"] = "untrusted-node:latest"
    with pytest.raises(ValueError, match="release"):
        release.reuse_images(current, previous)


def test_changed_node_source_is_rebuilt():
    current = release.plan(ROOT, "registry.example.com", "operator", "v0.3.1", "c" * 40)
    previous = deepcopy(current)
    previous.update(
        status="published",
        images={
            name: component["tag"].rsplit(":", 1)[0] + "@sha256:" + "b" * 64
            for name, component in previous["components"].items()
        },
    )
    previous["components"]["node"]["context"] = (
        "https://github.com/livepeer/node.git#" + "d" * 40
    )
    release.reuse_images(current, previous)
    assert "reuse" not in current["components"]["node"]


def test_cpu_publication_never_builds_pulls_or_pushes_the_reused_node(tmp_path):
    previous = release.plan(
        ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40
    )
    previous.update(
        status="published",
        images={
            name: component["tag"].rsplit(":", 1)[0] + "@sha256:" + "b" * 64
            for name, component in previous["components"].items()
        },
    )
    planned = release.plan(ROOT, "registry.example.com", "operator", "v0.3.1", "c" * 40)
    release.reuse_images(planned, previous)
    calls = []

    def docker(*args, capture=False):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps([args[-1].rsplit(":", 1)[0] + "@sha256:" + "e" * 64])
        return ""

    output = tmp_path / "cpu-release"
    release.publish(ROOT, planned, output, docker)
    assert len([call for call in calls if call[0] == "push"]) == 3
    assert not any(
        "livepeer-node" in part or "lightx2v-engine" in part
        for call in calls
        for part in call
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "published"
    assert manifest["images"]["node"] == previous["images"]["node"]


def test_release_plan_contains_only_cpu_roles_and_pins_node_source():
    plan = release.plan(ROOT, "registry.example.com", "operator", "v0.3.0", "a" * 40)
    assert set(plan["components"]) == {
        "runner",
        "controller",
        "node",
        "model-tools",
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
    assert plan["schema_version"] == 2 and plan["scope"] == "cpu"
    assert "engine_inputs" not in plan
    assert "deploy/docker/lightx2v-engine.Dockerfile" not in plan["input_sha256"]
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
    assert "_ENGINE_IMAGE=" not in env
    assert len([call for call in calls if call[0] == "push"]) == 4
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
    engines = tmp_path / ".engine-images.env"
    engine_values = "LIGHTX2V_ENGINE_IMAGE=sha256:" + "c" * 64 + "\n"
    engines.write_text(engine_values)
    destination = tmp_path / "selected.env"
    release.pull(
        ROOT, manifest, destination, lambda *args, **kwargs: calls.append(args)
    )
    assert set(calls) == {("pull", image) for image in manifest["images"].values()}
    assert len(calls) == 4
    assert destination.read_text() == release.deployment_env(manifest)
    assert engines.read_text() == engine_values
    original = destination.read_bytes()
    calls.clear()
    with pytest.raises(ValueError, match="existing env"):
        release.pull(
            ROOT, manifest, destination, lambda *args, **kwargs: calls.append(args)
        )
    assert not calls and destination.read_bytes() == original
