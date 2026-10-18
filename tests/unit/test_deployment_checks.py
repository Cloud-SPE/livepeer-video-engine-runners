"""Preparation checks inspect explicit settings, never create Docker resources."""

from video_runners.tools.deployment_check import check_deployment
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def prepared_deployment(tmp_path):
    cache = tmp_path / "cache"
    models = tmp_path / "models"
    cache.mkdir()
    models.mkdir()
    (models / "weight.bin").write_bytes(b"weights")
    asset = {
        "repo": "example/video",
        "revision": "a" * 40,
        "storage": "models",
        "directory": "example",
    }
    receipts = cache / "livepeer-assets"
    receipts.mkdir()
    (receipts / "sglang-example.json").write_text(
        json.dumps(
            {
                "engine": "sglang",
                "model": "example",
                "repo": asset["repo"],
                "revision": asset["revision"],
                "ready": True,
                "plan_sha256": hashlib.sha256(
                    json.dumps(asset, sort_keys=True).encode()
                ).hexdigest(),
                "files": [
                    {"storage": "models", "path": "weight.bin", "size": len(b"weights")}
                ],
            }
        )
    )
    public = tmp_path / "all.json"
    public.write_text(
        json.dumps(
            {
                "default": "example",
                "models": [
                    {
                        "id": "example",
                        "engine": "openai-videos",
                        "command": ["engine"],
                        "port": 9100,
                    }
                ],
            }
        )
    )
    image = "registry.example.com/engine@sha256:" + "a" * 64
    trusted = tmp_path / "controller.json"
    trusted.write_text(
        json.dumps(
            {
                "namespace": "check",
                "network": "check-engine",
                "gpu": "${ENGINE_GPU_UUID}",
                "models": {
                    "example": {
                        "image": image,
                        "command": ["engine"],
                        "mounts": [
                            {
                                "type": "volume",
                                "source": "check-hf",
                                "target": "/cache",
                                "read_only": False,
                            },
                            {
                                "type": "volume",
                                "source": "check-models",
                                "target": "/models",
                                "read_only": False,
                            },
                        ],
                    }
                },
            }
        )
    )
    config = {
        "services": {
            "runner": {
                "image": "runner:local",
                "command": [
                    "--lifecycle=managed",
                    "--catalog=models/all.json",
                    "--model=example",
                ],
                "environment": {
                    "RUNNER_ADMIN_TOKEN": "PRIVATE_ADMIN_SENTINEL",
                    "ENGINE_CONTROLLER_TOKEN": "PRIVATE_CONTROLLER_SENTINEL",
                    "LIVEPEER_BOOTSTRAP_SECRET": "PRIVATE_BOOTSTRAP_SENTINEL",
                },
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(public),
                        "target": "/app/models/all.json",
                        "read_only": True,
                    }
                ],
            },
            "controller": {
                "image": "controller:local",
                "environment": {
                    "ENGINE_GPU_UUID": "GPU-selected",
                    "ENGINE_CONTROLLER_TOKEN": "PRIVATE_CONTROLLER_SENTINEL",
                    "HF_CACHE_VOLUME": "check-hf",
                    "MODELS_VOLUME": "check-models",
                },
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(trusted),
                        "target": "/config/catalog.json",
                        "read_only": True,
                    }
                ],
            },
        },
        "networks": {"engine": {"name": "check-engine"}},
        "volumes": {
            "controller-state": {"name": "check-state", "external": True},
            "gpu-leases": {"name": "check-leases", "external": True},
        },
    }
    calls = []

    def probe(*command):
        calls.append(command)
        if command[:2] == ("docker", "version"):
            return json.dumps({"MinAPIVersion": "1.44", "ApiVersion": "1.56"})
        if command[:2] == ("docker", "info"):
            return json.dumps({"Runtimes": {"nvidia": {}}, "MemTotal": 64 * 1024**3})
        if command[0] == "nvidia-smi":
            return "GPU-selected\nGPU-other"
        if command[:3] == ("docker", "image", "inspect"):
            return json.dumps([{"Id": "sha256:" + "a" * 64}])
        if command[:3] == ("docker", "volume", "inspect"):
            name = command[-1]
            return json.dumps(
                [
                    {
                        "Name": name,
                        "Mountpoint": str(cache if name == "check-hf" else models),
                    }
                ]
            )
        raise AssertionError(f"Unexpected or mutating command: {command}")

    return config, {"models": {"sglang": {"example": asset}}}, probe, calls, image


def test_missing_managed_services_fail_with_guidance():
    result = check_deployment({"services": {}})
    assert result["ready"] is False
    assert result["checks"] == [
        {
            "check": "managed-services",
            "ready": False,
            "detail": "runner and controller services are required",
            "hint": "Select compose.prod.yml or compose.dev.yml and the intended supporting files.",
        }
    ]


def test_missing_prepared_engine_image_fails_without_staging_it(prepared_deployment):
    config, manifest, probe, calls, engine_image = prepared_deployment

    def unavailable(*command):
        if command == ("docker", "image", "inspect", engine_image):
            raise subprocess.CalledProcessError(
                1, command, stderr="PRIVATE_REGISTRY_ERROR"
            )
        return probe(*command)

    result = check_deployment(config, manifest=manifest, probe=unavailable)
    assert result["ready"] is False
    assert any(
        row["check"] == "engine-image:example" and not row["ready"]
        for row in result["checks"]
    )
    assert "PRIVATE" not in json.dumps(result)
    assert all(
        command[:2]
        in {
            ("docker", "version"),
            ("docker", "info"),
            ("docker", "image"),
            ("docker", "volume"),
        }
        or command[0] == "nvidia-smi"
        for command in calls
    )


def test_missing_external_volume_is_not_created(prepared_deployment):
    config, manifest, probe, calls, _ = prepared_deployment

    def unavailable(*command):
        if command == ("docker", "volume", "inspect", "check-models"):
            raise subprocess.CalledProcessError(1, command)
        return probe(*command)

    result = check_deployment(config, manifest=manifest, probe=unavailable)
    assert result["ready"] is False
    assert any(
        row["check"] == "volume:check-models" and not row["ready"]
        for row in result["checks"]
    )
    assert not any("create" in command or "run" in command for command in calls)


def test_reserved_gpu_must_exist_on_the_checked_host(prepared_deployment):
    config, manifest, probe, _, _ = prepared_deployment
    config["services"]["controller"]["environment"]["ENGINE_GPU_UUID"] = "GPU-missing"
    result = check_deployment(config, manifest=manifest, probe=probe)
    assert result["ready"] is False
    assert any(
        row["check"] == "gpu-assignment" and not row["ready"]
        for row in result["checks"]
    )


def test_profile_with_a_deleted_weight_is_not_ready(prepared_deployment):
    config, manifest, probe, _, _ = prepared_deployment
    volumes = json.loads(probe("docker", "volume", "inspect", "check-models"))
    (Path(volumes[0]["Mountpoint"]) / "weight.bin").unlink()
    result = check_deployment(config, manifest=manifest, probe=probe)
    assert result["ready"] is False
    assert any(
        row["check"] == "assets:example" and not row["ready"]
        for row in result["checks"]
    )


def test_initializer_check_preserves_private_settings_and_redacts_compose_output(
    prepared_deployment, tmp_path, monkeypatch, capsys
):
    from video_runners.tools import deployment_check, init_deployment

    config, manifest, probe, calls, _ = prepared_deployment
    settings = tmp_path / "provider.env"
    settings.write_text("BOOTSTRAP_SECRET=PRIVATE_SETTINGS_SENTINEL\n")
    assets = tmp_path / "assets.json"
    assets.write_text(json.dumps(manifest))

    def commands(*command):
        if command[:3] == ("docker", "context", "inspect"):
            return json.dumps("unix:///run/docker.sock")
        if command[:2] == ("docker", "compose"):
            calls.append(command)
            assert command[-3:] == ("config", "--format", "json")
            return json.dumps(config)
        return probe(*command)

    monkeypatch.setattr(deployment_check, "probe_command", commands)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "init",
            "--check",
            "--env-file",
            str(settings),
            "--assets-manifest",
            str(assets),
        ],
    )
    before = settings.read_bytes()
    init_deployment.main()
    output = capsys.readouterr().out
    assert json.loads(output)["ready"] is True
    assert "PRIVATE" not in output
    assert settings.read_bytes() == before
    assert calls


def test_mismatched_control_credentials_are_reported_without_values(
    prepared_deployment,
):
    config, manifest, probe, _, _ = prepared_deployment
    config["services"]["runner"]["environment"][
        "ENGINE_CONTROLLER_TOKEN"
    ] = "PRIVATE_WRONG_TOKEN"
    result = check_deployment(config, manifest=manifest, probe=probe)
    assert result["ready"] is False
    assert any(
        row["check"] == "credentials" and not row["ready"] for row in result["checks"]
    )
    assert "PRIVATE" not in json.dumps(result)


def test_missing_cpu_runner_image_is_reported(prepared_deployment):
    config, manifest, probe, _, _ = prepared_deployment

    def unavailable(*command):
        if command == ("docker", "image", "inspect", "runner:local"):
            raise subprocess.CalledProcessError(1, command)
        return probe(*command)

    result = check_deployment(config, manifest=manifest, probe=unavailable)
    assert result["ready"] is False
    assert any(
        row["check"] == "service-image:runner" and not row["ready"]
        for row in result["checks"]
    )


def test_unselected_optional_profile_does_not_require_its_assets(prepared_deployment):
    config, manifest, probe, calls, _ = prepared_deployment
    runner_catalog = Path(config["services"]["runner"]["volumes"][0]["source"])
    public = json.loads(runner_catalog.read_text())
    public["models"].append(dict(public["models"][0], id="optional"))
    runner_catalog.write_text(json.dumps(public))
    policy_path = Path(config["services"]["controller"]["volumes"][0]["source"])
    policy = json.loads(policy_path.read_text())
    optional_image = "registry.example.com/optional@sha256:" + "b" * 64
    policy["models"]["optional"] = dict(
        policy["models"]["example"], image=optional_image
    )
    policy_path.write_text(json.dumps(policy))
    result = check_deployment(config, manifest=manifest, probe=probe)
    assert result["ready"] is True
    assert not any(command[-1] == optional_image for command in calls)
    assert not any(row["check"] == "assets:optional" for row in result["checks"])


def test_compose_errors_do_not_echo_private_values(
    prepared_deployment, tmp_path, monkeypatch
):
    from video_runners.tools import deployment_check

    settings = tmp_path / "provider.env"
    settings.write_text("BOOTSTRAP_SECRET=PRIVATE_SETTINGS_SENTINEL\n")

    def unavailable(*command):
        if command[:3] == ("docker", "context", "inspect"):
            return json.dumps("unix:///run/docker.sock")
        raise subprocess.CalledProcessError(
            1, command, output="PRIVATE_STDOUT", stderr="PRIVATE_STDERR"
        )

    monkeypatch.setattr(deployment_check, "probe_command", unavailable)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    result = deployment_check.check_configuration(settings)
    assert result["ready"] is False
    assert "PRIVATE" not in json.dumps(result)


def test_named_runtime_absence_does_not_claim_device_request_failure(
    prepared_deployment,
):
    config, manifest, probe, _, _ = prepared_deployment

    def no_named_runtime(*command):
        result = probe(*command)
        if command[:2] == ("docker", "info"):
            info = json.loads(result)
            info["Runtimes"] = {"runc": {}}
            return json.dumps(info)
        return result

    result = check_deployment(config, manifest=manifest, probe=no_named_runtime)
    assert result["ready"] is True


def test_priced_catalog_filename_does_not_change_asset_profile_mapping(
    prepared_deployment,
):
    config, manifest, probe, _, _ = prepared_deployment
    mount = config["services"]["runner"]["volumes"][0]
    original = Path(mount["source"])
    renamed = original.with_name("operator-priced-catalog.json")
    original.rename(renamed)
    mount["source"] = str(renamed)
    assert check_deployment(config, manifest=manifest, probe=probe)["ready"] is True


def test_shell_dollars_in_trusted_commands_follow_controller_expansion_rules(
    prepared_deployment,
):
    config, manifest, probe, _, _ = prepared_deployment
    path = Path(config["services"]["controller"]["volumes"][0]["source"])
    policy = json.loads(path.read_text())
    policy["models"]["example"]["command"] = [
        "sh",
        "-c",
        "engine --prior-exit=$? --pid=$$",
    ]
    path.write_text(json.dumps(policy))
    assert check_deployment(config, manifest=manifest, probe=probe)["ready"] is True
