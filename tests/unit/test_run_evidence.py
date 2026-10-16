"""Receipts and host leases need no Docker, GPU, keys or remote services."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from video_runners.tools import evidence

ROOT = Path(__file__).resolve().parents[2]


def test_receipts_are_unique_private_and_preserve_partial_failures(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RUNNER_ADMIN_TOKEN", "private-sentinel")
    first = evidence.RunReceipt(ROOT, tmp_path, "cpu-managed")
    second = evidence.RunReceipt(ROOT, tmp_path, "cpu-managed")
    assert first.id != second.id
    assert first.data["source"]["revision"]
    with pytest.raises(RuntimeError):
        with first:
            first.result({"step": "one", "status": "passed"})
            raise RuntimeError("url-with-private-sentinel")
    path = first.directory / "receipt.json"
    stored = json.loads(path.read_text())
    assert stored["status"] == "failed" and stored["outcome"] == "unknown"
    assert stored["results"] == [{"step": "one", "status": "passed"}]
    assert "private-sentinel" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert first.directory.stat().st_mode & 0o777 == 0o700
    with second:
        second.data["outcome"] = "readiness_only"
    assert second.data["outcome"] == "readiness_only"


def test_child_lease_does_not_unlock_parent_and_competitor_is_excluded(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(evidence, "LOCK_ROOT", tmp_path)
    code = """
import sys
from pathlib import Path
from video_runners.tools import evidence
evidence.LOCK_ROOT = Path(sys.argv[1])
try:
    with evidence.HostLease():
        pass
except RuntimeError:
    sys.exit(7)
"""
    with evidence.HostLease() as lease:
        inherited = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            pass_fds=(lease.fd,),
            env=lease.child_env("test"),
            timeout=10,
        )
        assert inherited.returncode == 0
        competitor = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)], timeout=10
        )
        assert competitor.returncode == 7
    assert (
        subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)], timeout=10
        ).returncode
        == 0
    )


def test_gpu_validator_records_failure_and_never_resubmits(tmp_path, monkeypatch):
    from video_runners.tools import validate_gpu

    monkeypatch.setattr(evidence, "LOCK_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate-gpu",
            "--engine",
            "sglang",
            "--output-dir",
            str(tmp_path),
            "--repeat",
            "2",
        ],
    )
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, ["client"])

    monkeypatch.setattr(validate_gpu.subprocess, "run", fail)
    monkeypatch.setattr(
        evidence,
        "source_identity",
        lambda root: {"revision": "a" * 40, "dirty": False, "worktree_id": "b" * 10},
    )
    with pytest.raises(subprocess.CalledProcessError):
        validate_gpu.main()
    assert len(calls) == 1
    receipt = json.loads(next(tmp_path.glob("vr-*/receipt.json")).read_text())
    assert receipt["status"] == "failed" and receipt["outcome"] == "unknown"
    assert receipt["inputs"]["assets"][0]["revision"]
    assert receipt["inputs"]["observed_engine"] is None


def test_cpu_failure_logs_redact_known_tokens(tmp_path, monkeypatch):
    from video_runners.tools import cpu_harness

    receipt = evidence.RunReceipt(ROOT, tmp_path, "cpu-managed")
    harness = cpu_harness.CPUHarness.__new__(cpu_harness.CPUHarness)
    harness.receipt, harness.path, harness.env = (
        receipt,
        tmp_path / "resources.json",
        {},
    )
    harness.values = {"ENGINE_CONTROLLER_TOKEN": "sensitive-test-token"}

    class Daemon:
        def inspect(self, *args):
            return {"exists": True}

    harness.docker = Daemon()
    monkeypatch.setattr(
        cpu_harness,
        "capture",
        lambda *args: {
            "resources": [{"kind": "container", "id": "a" * 64, "role": "controller"}]
        },
    )

    def run(args, **kwargs):
        if args == ["failing-step"]:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, "error sensitive-test-token")

    monkeypatch.setattr(cpu_harness.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        harness.command("startup", ["failing-step"])
    log = (receipt.directory / "controller.log").read_text()
    assert "sensitive-test-token" not in log and "[redacted]" in log


def test_cpu_failure_reports_step_log_when_inspection_fails(
    tmp_path, monkeypatch, capsys
):
    from video_runners.tools import cpu_harness

    receipt = evidence.RunReceipt(ROOT, tmp_path, "cpu-managed")
    harness = cpu_harness.CPUHarness.__new__(cpu_harness.CPUHarness)
    harness.receipt, harness.path, harness.env = (
        receipt,
        tmp_path / "resources.json",
        {},
    )
    harness.values = {"ENGINE_CONTROLLER_TOKEN": "sensitive-test-token"}
    harness.docker = object()

    def fail(args, **kwargs):
        kwargs["stdout"].write("Docker API version unsupported: sensitive-test-token\n")
        raise subprocess.CalledProcessError(1, args)

    def unavailable(*args):
        raise RuntimeError("inspection unavailable")

    monkeypatch.setattr(cpu_harness.subprocess, "run", fail)
    monkeypatch.setattr(cpu_harness, "capture", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        harness.command("startup", ["failing-step"])

    diagnostic = capsys.readouterr().err
    assert "Docker API version unsupported" in diagnostic
    assert "[redacted]" in diagnostic
    assert "sensitive-test-token" not in diagnostic


def test_lifecycle_diagnostics_refuse_sensitive_fields(caplog):
    import logging
    from video_runners.diagnostics import event

    with pytest.raises(ValueError, match="unsupported"):
        event(logging.getLogger("test"), "example", token="private-sentinel")
    assert "private-sentinel" not in caplog.text
