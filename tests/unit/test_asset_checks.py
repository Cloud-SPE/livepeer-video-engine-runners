"""Offline checks of explicitly prepared assets; no daemon or downloads."""

import json
import hashlib
import sys
import types

import pytest

from video_runners.tools import prepare_weights

from video_runners.tools.prepare_weights import check_assets


def test_unprepared_assets_fail_without_creating_directories(tmp_path):
    cache = tmp_path / "cache"
    models = tmp_path / "models"
    spec = {"repo": "example/video", "revision": "a" * 40, "storage": "hf"}
    result = check_assets("sglang", "example", spec, cache, models)
    assert result["ready"] is False
    assert "preparation receipt is missing" in result["missing"]
    assert not cache.exists()
    assert not models.exists()


def test_stale_preparation_revision_is_not_ready(tmp_path):
    cache = tmp_path / "cache"
    receipts = cache / "livepeer-assets"
    receipts.mkdir(parents=True)
    spec = {"repo": "example/video", "revision": "a" * 40, "storage": "hf"}
    (receipts / "sglang-example.json").write_text(
        json.dumps(
            {
                "engine": "sglang",
                "model": "example",
                "repo": spec["repo"],
                "revision": "b" * 40,
                "ready": True,
            }
        )
    )
    result = check_assets("sglang", "example", spec, cache, tmp_path / "models")
    assert result["ready"] is False
    assert (
        "preparation receipt does not match the selected pinned assets"
        in result["missing"]
    )


def test_receipt_without_file_inventory_cannot_prove_assets_ready(tmp_path):
    cache = tmp_path / "cache"
    receipts = cache / "livepeer-assets"
    receipts.mkdir(parents=True)
    spec = {"repo": "example/video", "revision": "a" * 40, "storage": "hf"}
    (receipts / "sglang-example.json").write_text(
        json.dumps(
            {
                "engine": "sglang",
                "model": "example",
                "repo": spec["repo"],
                "revision": spec["revision"],
                "ready": True,
            }
        )
    )
    result = check_assets("sglang", "example", spec, cache, tmp_path / "models")
    assert result["ready"] is False
    assert (
        "file inventory is missing; repeat preparation to record cached assets"
        in result["missing"]
    )


def prepared_fixture(tmp_path):
    cache = tmp_path / "cache"
    models = tmp_path / "models"
    receipts = cache / "livepeer-assets"
    receipts.mkdir(parents=True)
    models.mkdir()
    weight = models / "video.safetensors"
    weight.write_bytes(b"saved model weights")
    spec = {
        "repo": "example/video",
        "revision": "a" * 40,
        "storage": "models",
        "directory": "example",
    }
    saved = {
        "engine": "lightx2v",
        "model": "example",
        "repo": spec["repo"],
        "revision": spec["revision"],
        "ready": True,
        "plan_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode()
        ).hexdigest(),
        "files": [
            {
                "storage": "models",
                "path": weight.name,
                "size": len(b"saved model weights"),
            }
        ],
    }
    receipt = receipts / "lightx2v-example.json"
    receipt.write_text(json.dumps(saved))
    return cache, models, weight, spec, receipt, saved


def test_deleted_weight_fails_even_when_receipt_says_ready(tmp_path):
    cache, models, weight, spec, _, _ = prepared_fixture(tmp_path)
    weight.unlink()
    result = check_assets("lightx2v", "example", spec, cache, models)
    assert result["ready"] is False
    assert (
        "models:video.safetensors is missing or has a different size"
        in result["missing"]
    )


def test_changed_extra_asset_revision_requires_new_preparation(tmp_path):
    cache, models, _, spec, _, _ = prepared_fixture(tmp_path)
    assert check_assets("lightx2v", "example", spec, cache, models)["ready"]
    spec["extra_files"] = [
        {"repo": "example/lora", "revision": "b" * 40, "filename": "lora.safetensors"}
    ]
    result = check_assets("lightx2v", "example", spec, cache, models)
    assert result["ready"] is False
    assert "preparation plan has changed; repeat preparation" in result["missing"]


def test_preparation_records_inventory_and_offline_check_preserves_files(
    tmp_path, monkeypatch, capsys
):
    cache = tmp_path / "cache"
    models = tmp_path / "models"
    location = models / "example"
    location.mkdir(parents=True)
    weight = location / "model.safetensors"
    weight.write_bytes(b"cached weights")
    metadata = location / ".cache" / "download.metadata"
    metadata.parent.mkdir()
    metadata.write_text("download bookkeeping")
    spec = {
        "repo": "example/video",
        "revision": "a" * 40,
        "storage": "models",
        "directory": "example",
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "defaults": {"lightx2v": "example"},
                "models": {"lightx2v": {"example": spec}},
            }
        )
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(
            snapshot_download=lambda *args, **kwargs: str(location),
            hf_hub_download=lambda *args, **kwargs: pytest.fail(
                "unexpected extra download"
            ),
        ),
    )
    arguments = [
        "prepare_weights",
        "lightx2v",
        "--manifest",
        str(manifest),
        "--cache-dir",
        str(cache),
        "--models-dir",
        str(models),
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    prepare_weights.main()
    receipt = cache / "livepeer-assets/lightx2v-example.json"
    saved = json.loads(receipt.read_text())
    assert saved["files"] == [
        {
            "storage": "models",
            "path": "example/model.safetensors",
            "size": len(b"cached weights"),
        }
    ]
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    monkeypatch.setattr(sys, "argv", arguments + ["--check"])
    prepare_weights.main()
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["ready"] is True
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }


def test_hf_offline_main_ref_must_point_to_the_prepared_revision(tmp_path):
    cache, models, _, spec, receipt, saved = prepared_fixture(tmp_path)
    spec["storage"] = "hf"
    saved["plan_sha256"] = hashlib.sha256(
        json.dumps(spec, sort_keys=True).encode()
    ).hexdigest()
    receipt.write_text(json.dumps(saved))
    ref = cache / "hub/models--example--video/refs/main"
    ref.parent.mkdir(parents=True)
    ref.write_text(spec["revision"])
    assert check_assets("lightx2v", "example", spec, cache, models)["ready"]
    ref.write_text("b" * 40)
    result = check_assets("lightx2v", "example", spec, cache, models)
    assert result["ready"] is False
    assert "offline main ref does not match the pinned revision" in result["missing"]


def test_receipt_symlink_cannot_escape_the_cache_volume(tmp_path):
    cache, models, _, spec, receipt, saved = prepared_fixture(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(saved))
    receipt.unlink()
    receipt.symlink_to(outside)
    result = check_assets("lightx2v", "example", spec, cache, models)
    assert result["ready"] is False
    assert "preparation receipt escapes its asset volume" in result["missing"]


def test_numeric_ready_flag_does_not_replace_a_successful_preparation(tmp_path):
    cache, models, _, spec, receipt, saved = prepared_fixture(tmp_path)
    saved["ready"] = 1
    receipt.write_text(json.dumps(saved))
    assert check_assets("lightx2v", "example", spec, cache, models)["ready"] is False


def test_inventory_includes_locally_converted_required_weights(tmp_path):
    cache = tmp_path / "cache"
    models = tmp_path / "models"
    location = models / "source"
    location.mkdir(parents=True)
    (location / "config.json").write_text("{}")
    converted = models / "converted.safetensors"
    converted.write_bytes(b"converted model")
    spec = {
        "storage": "models",
        "required_files": ["converted.safetensors", "source/config.json"],
    }
    inventory = prepare_weights.asset_inventory(spec, location, cache, models)
    assert {item["path"] for item in inventory} == {
        "converted.safetensors",
        "source/config.json",
    }
    assert len(inventory) == 2


def test_empty_weight_file_does_not_count_as_prepared(tmp_path):
    cache, models, weight, spec, receipt, saved = prepared_fixture(tmp_path)
    weight.write_bytes(b"")
    saved["files"][0]["size"] = 0
    receipt.write_text(json.dumps(saved))
    result = check_assets("lightx2v", "example", spec, cache, models)
    assert result["ready"] is False
    assert "models:video.safetensors is empty" in result["missing"]


def test_truncated_weight_is_rejected_with_original_receipt(tmp_path):
    cache, models, weight, spec, _, _ = prepared_fixture(tmp_path)
    weight.write_bytes(b"truncated")
    result = check_assets("lightx2v", "example", spec, cache, models)
    assert result["ready"] is False
    assert (
        "models:video.safetensors is missing or has a different size"
        in result["missing"]
    )


def test_mutable_revision_cannot_count_as_a_pinned_preparation(tmp_path):
    cache, models, _, spec, receipt, saved = prepared_fixture(tmp_path)
    spec["revision"] = saved["revision"] = "main"
    saved["plan_sha256"] = hashlib.sha256(
        json.dumps(spec, sort_keys=True).encode()
    ).hexdigest()
    receipt.write_text(json.dumps(saved))
    result = check_assets("lightx2v", "example", spec, cache, models)
    assert result["ready"] is False
    assert (
        "asset plan requires immutable revisions and volume-relative paths"
        in result["missing"]
    )
