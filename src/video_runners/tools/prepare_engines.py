#!/usr/bin/env python3
"""Stage pinned GPU images and build the separate LightX2V engine image."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from video_runners.tools.operator_io import read_env

ROOT = Path(__file__).resolve().parents[3]


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def stage(engine: str, images: dict) -> str:
    if engine != "lightx2v":
        image = images[engine]
        found = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if found.returncode:
            run("docker", "pull", image)
        return image
    run(
        "docker",
        "buildx",
        "build",
        "--builder",
        os.environ.get("BUILDX_BUILDER", "default"),
        "--load",
        "-f",
        "deploy/docker/lightx2v-engine.Dockerfile",
        "--build-arg",
        "LIGHTX2V_IMAGE=" + images["lightx2v_base"],
        "--build-arg",
        "LIGHTX2V_COMMIT=" + images["lightx2v_commit"],
        "-t",
        "livepeer-video-lightx2v-engine:local",
        ".",
    )
    # A local build has no registry digest. Its immutable image ID is accepted
    # by Docker and the controller; never authorize a mutable local GPU tag.
    return run(
        "docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        "livepeer-video-lightx2v-engine:local",
        capture=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "engine",
        choices=("sglang", "lightx2v", "vllm-omni", "all"),
        default="all",
        nargs="?",
    )
    args = parser.parse_args()
    images = json.loads((ROOT / "configs/engine-images.json").read_text())
    engines = (
        ("sglang", "vllm-omni", "lightx2v") if args.engine == "all" else (args.engine,)
    )
    destination = ROOT / ".engine-images.env"
    values = read_env(destination)
    for engine in engines:
        image = stage(engine, images)
        values[engine.upper().replace("-", "_") + "_ENGINE_IMAGE"] = image
        # Preserve completed work if a later engine build fails.
        with tempfile.NamedTemporaryFile(mode="w", dir=ROOT, delete=False) as file:
            file.write(
                "# Generated immutable image references; pass with docker compose --env-file .engine-images.env.\n"
            )
            for key, value in sorted(values.items()):
                file.write(f"{key}={value}\n")
            name = file.name
        os.replace(name, destination)
        print(f"{engine}: {image}", flush=True)


if __name__ == "__main__":
    main()
