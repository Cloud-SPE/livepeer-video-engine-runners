"""Generated outputs, independent authorities and preparation agreement."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

from video_runners.tools import sync_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checkout(tmp_path):
    for directory in ("models", "configs", "deploy", "src"):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    (tmp_path / "docs/reference").mkdir(parents=True)
    return tmp_path


def update(root, file, change):
    path = root / file
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def test_generated_catalogs_preserve_existing_definitions_and_order():
    for path, content in sync_config.generated_files(ROOT).items():
        if path.suffix == ".json":
            assert json.loads(content) == json.loads((ROOT / path).read_text())
            assert list(json.loads(content)["models"]) == list(
                json.loads((ROOT / path).read_text())["models"]
            )


def test_public_overrides_cannot_generate_trusted_launch_policy(checkout):
    expected = sync_config.combined_trusted(checkout / "configs/controller")
    update(
        checkout,
        "models/sglang.json",
        lambda value: value["models"][0].update(
            command=["untrusted"], mounts=[{"source": "/"}], price_usd_per_hour=7
        ),
    )
    assert sync_config.combined_trusted(checkout / "configs/controller") == expected
    public = sync_config.combined_public(checkout / "models")
    assert public["models"][0]["command"] == ["untrusted"]
    assert public["models"][0]["price_usd_per_hour"] == 7


def test_trusted_generator_refuses_conflicting_global_policy(checkout):
    update(
        checkout,
        "configs/controller/lightx2v.json",
        lambda value: value.update(network="other-network"),
    )
    with pytest.raises(ValueError, match="trusted headers disagree"):
        sync_config.combined_trusted(checkout / "configs/controller")


@pytest.mark.parametrize(
    "file,change,message",
    [
        (
            "configs/controller/sglang.json",
            lambda value: value["models"]["fastwan2.1-t2v-1.3b"].update(
                image="repo:mutable"
            ),
            "trusted image disagrees",
        ),
        (
            "configs/model-assets.json",
            lambda value: value["defaults"].update(sglang="other-model"),
            "defaults must agree",
        ),
        (
            "configs/model-assets.json",
            lambda value: value["models"]["sglang"]["fastwan2.1-t2v-1.3b"].update(
                revision="main"
            ),
            "asset revisions must be full commits",
        ),
        (
            "configs/model-assets.json",
            lambda value: value["models"]["lightx2v"]["wan2.1-t2v-1.3b"].update(
                directory="wrong-directory"
            ),
            "trusted model path disagrees",
        ),
        (
            "models/sglang.json",
            lambda value: value["models"].append(deepcopy(value["models"][0])),
            "IDs must agree without duplicates",
        ),
        (
            "configs/engine-images.json",
            lambda value: value.update(sglang="repo:mutable"),
            "must be pinned by registry digest",
        ),
    ],
)
def test_source_disagreement_is_actionable(checkout, file, change, message):
    update(checkout, file, change)
    assert any(message in error for error in sync_config.check_sources(checkout))


@pytest.mark.parametrize(
    "file,original,replacement,message",
    [
        (
            "deploy/compose/external.yml",
            "${EXTERNAL_ENGINE_IMAGE:-lmsysorg/sglang@sha256:",
            "${EXTERNAL_ENGINE_IMAGE:-wrong@sha256:",
            "EXTERNAL_ENGINE_IMAGE default disagrees",
        ),
        (
            "deploy/docker/lightx2v-engine.Dockerfile",
            "ARG LIGHTX2V_COMMIT=",
            "ARG LIGHTX2V_COMMIT=unreviewed-",
            "LIGHTX2V_COMMIT disagrees",
        ),
    ],
)
def test_preparation_and_deployment_pins_cannot_drift(
    checkout, file, original, replacement, message
):
    path = checkout / file
    changed = path.read_text().replace(original, replacement)
    if file.endswith(".yml"):
        image = json.loads((checkout / "configs/engine-images.json").read_text())[
            "sglang"
        ]
        # An old correct default in a comment must not mask the active image.
        changed = f"# image: ${{EXTERNAL_ENGINE_IMAGE:-{image}}}\n" + changed
    path.write_text(changed)
    assert any(message in error for error in sync_config.check_sources(checkout))


def test_check_is_read_only_and_write_refuses_disagreeing_sources(
    checkout, monkeypatch
):
    monkeypatch.setattr(sync_config, "ROOT", checkout)
    monkeypatch.setattr(sys, "argv", ["sync-config"])
    before = (checkout / "models/all.json").read_bytes()
    with pytest.raises(SystemExit) as result:
        sync_config.main()
    assert result.value.code == 1  # Reference file has not been generated here.
    assert not (checkout / "docs/reference/configuration.md").exists()
    assert (checkout / "models/all.json").read_bytes() == before
    monkeypatch.setattr(sys, "argv", ["sync-config", "--write"])
    sync_config.main()
    monkeypatch.setattr(sys, "argv", ["sync-config"])
    sync_config.main()
    path = checkout / "configs/controller/all.json"
    path.write_text("stale\n")
    update(
        checkout,
        "configs/model-assets.json",
        lambda value: value["defaults"].update(sglang="wrong"),
    )
    monkeypatch.setattr(sys, "argv", ["sync-config", "--write"])
    with pytest.raises(SystemExit) as result:
        sync_config.main()
    assert result.value.code == 1
    assert path.read_text() == "stale\n"


def test_reference_reads_source_without_executing_it_or_private_env(checkout):
    before = sync_config.configuration_reference(checkout)
    path = checkout / "src/video_runners/runner/app.py"
    path.write_text(
        "raise RuntimeError('must never execute')\n"
        + path.read_text().replace('default="bundled"', 'default="external"')
    )
    (checkout / ".env").write_text("RUNNER_ADMIN_TOKEN=private-test-sentinel\n")
    after = sync_config.configuration_reference(checkout)
    assert after != before
    assert "private-test-sentinel" not in after
    policy = checkout / "src/video_runners/controller/policy.py"
    policy.write_text(
        policy.read_text().replace(
            '"namespace", "network"', '"test_field", "namespace", "network"', 1
        )
    )
    assert "`test_field`" in sync_config.configuration_reference(checkout)


def test_fresh_catalogs_and_reference_pass_source_checks():
    assert sync_config.check_sources(ROOT) == []
    assert all(
        (ROOT / path).read_text() == content
        for path, content in sync_config.generated_files(ROOT).items()
    )
