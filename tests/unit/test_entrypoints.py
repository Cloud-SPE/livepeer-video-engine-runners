"""Installed runtime commands and standalone preparation launchers."""

from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "command,required",
    [
        ("video-runner", {"--catalog", "--lifecycle", "--delivery", "--busy"}),
        ("video-controller", {"--catalog", "--host", "--port"}),
        ("video-client", {"--model", "--discovery", "--signer", "--mode"}),
        ("video-stub-engine", {"--api", "--host", "--port"}),
    ],
)
def test_installed_cli_runs_outside_the_checkout(tmp_path, command, required):
    installed = subprocess.run(
        [str(Path(sys.executable).parent / command), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    options = re.compile(r"--[a-z][a-z-]*")
    assert required <= set(options.findall(installed.stdout))


def test_external_engine_launcher_needs_only_the_standard_library(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "src/video_runners/tools/engine_entrypoint.py"),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--catalog" in result.stdout and "--model" in result.stdout


def test_engine_preparation_runs_directly_from_its_source(tmp_path):
    result = subprocess.run(
        [str(ROOT / "src/video_runners/tools/prepare_engines.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "sglang" in result.stdout and "lightx2v" in result.stdout


@pytest.mark.parametrize(
    "script",
    [
        "init_deployment.py",
        "prepare_engines.py",
        "validate_all.py",
        "sync_config.py",
        "cpu_harness.py",
    ],
)
def test_standard_library_host_tools_run_before_package_installation(tmp_path, script):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "src/video_runners/tools" / script),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "usage:" in result.stdout
