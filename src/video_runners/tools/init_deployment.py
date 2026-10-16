#!/usr/bin/env python3
"""Create private deployment settings and durable external Docker volumes."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from video_runners.tools.operator_io import command_output as output


def choose_subnets() -> list[str]:
    ids = output("docker", "network", "ls", "-q").split()
    networks = json.loads(output("docker", "network", "inspect", *ids)) if ids else []
    used = [
        ipaddress.ip_network(c["Subnet"])
        for n in networks
        for c in (n.get("IPAM", {}).get("Config") or [])
        if c.get("Subnet")
    ]
    chosen = []
    for second in (30, *range(20, 30), 31, *range(16, 20)):
        for last in range(88, 255):
            candidate = ipaddress.ip_network(f"172.{second}.{last}.0/24")
            if all(
                candidate.version != n.version or not candidate.overlaps(n)
                for n in used
            ):
                chosen.append(f"172.{second}.{last}")
            if len(chosen) == 4:
                return chosen
    raise ValueError(
        "No unused subnet block found; configure the four prefixes manually"
    )


def choose_port(preferred: int) -> str:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine",
        choices=("all", "sglang", "lightx2v", "vllm-omni", "stub"),
        default="all",
    )
    parser.add_argument("--mode", choices=("managed", "external"), default="managed")
    parser.add_argument("--project", default="video-engines")
    parser.add_argument(
        "--existing-orchestrator",
        action="store_true",
        help="Create settings for an existing Livepeer node; edit URLs and its shared secret before starting",
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--gpu", default="", help="Reserved NVIDIA GPU UUID; auto-detects a single GPU"
    )
    args = parser.parse_args()
    if args.env_file.exists():
        parser.error(
            f"{args.env_file} already exists; preserve and edit it instead of overwriting"
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", args.project):
        parser.error("project must be at most 41 lowercase letters, digits and hyphens")
    if args.engine == "all" and args.mode == "external":
        parser.error("the combined catalog requires managed lifecycle")
    compose_version = output("docker", "compose", "version", "--short").lstrip("v")
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", compose_version)
    if not match or tuple(map(int, match.groups())) < (2, 24, 4):
        parser.error("Docker Compose 2.24.4 or newer is required")
    if args.mode == "managed":
        server = json.loads(output("docker", "version", "--format", "{{json .Server}}"))

        def protocol(value):
            return tuple(map(int, value.split(".")))

        if (
            not protocol(server["MinAPIVersion"])
            <= (1, 51)
            <= protocol(server["ApiVersion"])
        ):
            parser.error(
                "the Docker daemon must support API v1.51 for the socket proxy"
            )
    gpu = args.gpu
    if args.engine != "stub" and not gpu:
        identifiers = output(
            "nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"
        ).splitlines()
        if len(identifiers) != 1:
            parser.error("choose the reserved GPU with --gpu GPU-UUID")
        gpu = identifiers[0].strip()
    if gpu and not re.fullmatch(r"GPU-[A-Za-z0-9-]+", gpu):
        parser.error("--gpu must be a GPU UUID")
    prefixes = choose_subnets()
    values = {
        "COMPOSE_PROJECT_NAME": args.project,
        "ENGINE": args.engine,
        "MODEL": "",
        "ENGINE_CONTROLLER_CATALOG": "",
        "PUBLIC_MODEL_CATALOG": "",
        "ENGINE_GPU_UUID": gpu,
        "GPU_ID": gpu or "0",
        "BOOTSTRAP_SECRET": "" if args.existing_orchestrator else secrets.token_hex(32),
        "RUNNER_ADMIN_TOKEN": secrets.token_hex(32),
        "ENGINE_CONTROLLER_TOKEN": secrets.token_hex(32),
        "HF_CACHE_VOLUME": "livepeer-video-hf-cache",
        "MODELS_VOLUME": "livepeer-video-model-weights",
        "ENGINE_CACHE_VOLUME": "livepeer-video-engine-cache",
        "CONTROLLER_STATE_VOLUME": args.project + "-controller-state",
        "GPU_LEASE_VOLUME": "livepeer-video-gpu-leases",
        "SUBNET_PREFIX": prefixes[0],
        "CONTROL_SUBNET_PREFIX": prefixes[1],
        "ENGINE_SUBNET_PREFIX": prefixes[2],
        "DOCKER_API_SUBNET_PREFIX": prefixes[3],
        "ORCHESTRATOR_PORT": choose_port(8935),
        "RUNNER_ADMIN_PORT": choose_port(8990),
        "USE_EXISTING_ORCHESTRATOR": "1" if args.existing_orchestrator else "0",
        "ORCHESTRATOR_URL": "",
        "RUNNER_URL": "",
        "RUNNER_BIND_HOST": "",
        "RUNNER_PORT": "8989",
        "EXISTING_ORCHESTRATOR_NETWORK": "",
        "EXISTING_RUNNER_IP": "",
    }
    if args.mode == "external":
        images = json.loads(
            (
                Path(__file__).resolve().parents[3] / "configs/engine-images.json"
            ).read_text()
        )
        values["EXTERNAL_ENGINE_IMAGE"] = {
            "stub": "livepeer-video-stub-engine:local",
            "lightx2v": "livepeer-video-lightx2v-engine:local",
        }.get(args.engine, images.get(args.engine, ""))
    security = output("docker", "info", "--format", "{{json .SecurityOptions}}")
    values["DOCKER_SOCKET_PATH"] = os.environ.get(
        "DOCKER_SOCKET_PATH",
        (
            f"/run/user/{os.getuid()}/docker.sock"
            if "name=rootless" in security
            else "/var/run/docker.sock"
        ),
    )
    names = [
        values[key]
        for key in ("HF_CACHE_VOLUME", "MODELS_VOLUME", "ENGINE_CACHE_VOLUME")
    ]
    if args.mode == "managed":
        names += [values["CONTROLLER_STATE_VOLUME"], values["GPU_LEASE_VOLUME"]]
    for name in names:
        subprocess.run(
            [
                "docker",
                "volume",
                "create",
                "--label",
                "io.livepeer.video.persistent=true",
                name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    descriptor = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(
            "# Private settings generated by src/video_runners/tools/init_deployment.py.\n"
        )
        for key, value in values.items():
            file.write(f"{key}={value}\n")
    print(
        f"Created {args.env_file} (mode 0600) for {args.project}; external volumes: {', '.join(names)}"
    )


if __name__ == "__main__":
    main()
