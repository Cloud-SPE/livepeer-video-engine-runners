"""Read-only checks of an operator's resolved managed Compose deployment."""

import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from video_runners.catalog import load_catalog
from video_runners.controller.policy import Policy
from video_runners.tools.prepare_weights import check_assets

ROOT = Path(__file__).resolve().parents[3]


def probe_command(*args):
    return subprocess.run(
        args, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def argument(command, name, default=""):
    for index, value in enumerate(command):
        if value.startswith(name + "="):
            return value.split("=", 1)[1]
        if value == name and index + 1 < len(command):
            return command[index + 1]
    return default


def bound_file(service, target):
    target = str(PurePosixPath("/app") / target)
    for mount in service.get("volumes", []):
        if (
            mount.get("target") == target
            and mount.get("type") == "bind"
            and mount.get("read_only") is True
        ):
            return Path(mount["source"])
    raise ValueError("a read-only catalog bind is required")


def check_configuration(
    env_file, compose_files=(), extra_env_files=(), models=(), assets_manifest=None
):
    """Capture resolved private Compose data; emit only allowlisted diagnostics."""
    try:
        endpoint = os.environ.get("DOCKER_HOST", "")
        if not endpoint or os.environ.get("DOCKER_CONTEXT"):
            endpoint = json.loads(
                probe_command(
                    "docker",
                    "context",
                    "inspect",
                    "--format",
                    "{{json .Endpoints.docker.Host}}",
                )
            )
        if not endpoint.startswith("unix://"):
            return {
                "ready": False,
                "checks": [
                    dict(
                        check="local-daemon",
                        ready=False,
                        detail="This check needs the local Docker host's volume data.",
                        hint="Run on the Docker host with its Unix socket context; remote contexts cannot establish local asset readiness.",
                    )
                ],
            }
        files = [env_file]
        engine_env = ROOT / ".engine-images.env"
        if engine_env.is_file():
            files.append(engine_env)
        files.extend(extra_env_files)
        if not all(path.is_file() for path in files):
            raise ValueError("settings file missing")
        command = ["docker", "compose", "--project-directory", str(ROOT)]
        for path in files:
            command.extend(("--env-file", str(path.resolve())))
        for path in compose_files or [ROOT / "compose.prod.yml"]:
            command.extend(("-f", str(path.resolve())))
        config = json.loads(probe_command(*command, "config", "--format", "json"))
        manifest = json.loads(assets_manifest.read_text()) if assets_manifest else None
        return check_deployment(config, models=models, manifest=manifest)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {
            "ready": False,
            "checks": [
                dict(
                    check="configuration",
                    ready=False,
                    detail="Compose/private configuration could not be resolved.",
                    hint="Check the selected files, required variables and Docker access locally. Captured configuration and command errors are not printed.",
                )
            ],
        }


def check_deployment(config, models=(), manifest=None, probe=None):
    if not {"runner", "controller"} <= set(config.get("services", {})):
        return {
            "ready": False,
            "checks": [
                {
                    "check": "managed-services",
                    "ready": False,
                    "detail": "runner and controller services are required",
                    "hint": "Select compose.prod.yml or compose.dev.yml and the intended supporting files.",
                }
            ],
        }
    probe = probe or probe_command
    checks = []

    def add(name, ready, detail, hint=""):
        checks.append(dict(check=name, ready=ready, detail=detail, hint=hint))

    def result():
        return dict(ready=all(row["ready"] for row in checks), checks=checks)

    runner, controller = (config["services"][name] for name in ("runner", "controller"))
    try:
        if argument(runner["command"], "--lifecycle") != "managed":
            raise ValueError("managed checks require managed lifecycle")
        public_target = argument(runner["command"], "--catalog")
        public_path = bound_file(runner, public_target)
        public, _ = load_catalog(public_path)
        path = bound_file(
            controller,
            argument(
                controller.get("command", []), "--catalog", "/config/catalog.json"
            ),
        )
        environment = controller.get("environment", {})

        # Match the controller's expandvars grammar without reading this
        # client's environment or treating shell punctuation as placeholders.
        def replacement(match):
            key = match[1]
            key = key[1:-1] if key.startswith("{") else key
            return environment.get(key, match[0])

        raw = re.sub(r"\$(\w+|\{[^}]*\})", replacement, path.read_text())
        policy = Policy(json.loads(raw))
        selected = list(
            dict.fromkeys(models or [argument(runner["command"], "--model")])
        )
        if not all(selected) or any(
            model not in public or model not in policy.models for model in selected
        ):
            raise ValueError("choose profiles present in both catalogs")
    except (OSError, ValueError, KeyError, TypeError):
        add(
            "launch-policy",
            False,
            "Selected managed catalogs or model IDs are invalid.",
            "Use explicit --model IDs from both catalogs; review read-only binds, pinned images and controller substitutions.",
        )
        return result()
    add("launch-policy", True, "Selected models have valid trusted launch policies.")
    runner_env, controller_env = runner.get("environment", {}), controller.get(
        "environment", {}
    )
    token = controller_env.get("ENGINE_CONTROLLER_TOKEN", "")
    credentials = bool(
        token
        and runner_env.get("RUNNER_ADMIN_TOKEN")
        and runner_env.get("LIVEPEER_BOOTSTRAP_SECRET")
        and runner_env.get("ENGINE_CONTROLLER_TOKEN") == token
        and runner_env["RUNNER_ADMIN_TOKEN"] != token
    )
    add(
        "credentials",
        credentials,
        "Required bootstrap/admin/control settings and control-token agreement checked.",
        "Set nonempty credentials, independent admin/control tokens and matching runner/controller control tokens.",
    )
    add(
        "engine-network",
        config.get("networks", {}).get("engine", {}).get("name") == policy.network,
        "Trusted engine network checked against Compose.",
        "Align ENGINE_NETWORK and the trusted controller namespace/network settings.",
    )
    try:
        version = json.loads(probe("docker", "version", "--format", "{{json .Server}}"))

        def protocol(text):
            return tuple(map(int, text.split(".")))

        compatible = (
            protocol(version["MinAPIVersion"])
            <= (1, 51)
            <= protocol(version["ApiVersion"])
        )
        info = json.loads(probe("docker", "info", "--format", "{{json .}}"))
        add(
            "docker-api",
            compatible,
            "Docker API v1.51 compatibility checked.",
            "Use a daemon supporting API v1.51." if not compatible else "",
        )
        if policy.gpu:
            identifiers = probe(
                "nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"
            ).splitlines()
            add(
                "gpu-assignment",
                policy.gpu in identifiers,
                "Reserved GPU UUID presence checked.",
                "Run this command on the Docker host and select its GPU UUID; this check does not reserve VRAM.",
            )
        memory = max(
            policy.payloads[model]["HostConfig"].get("Memory", 0) for model in selected
        )
        add(
            "host-memory",
            memory <= info.get("MemTotal", 0),
            "Selected engine host-RAM limits checked against Docker host capacity.",
            "Review the trusted profile's host-RAM limit; this is not a free-memory or VRAM check.",
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        add(
            "docker-host",
            False,
            "Docker host/GPU metadata is unavailable.",
            "Run on the intended Docker host with daemon and NVIDIA inspection access.",
        )
    for role in ("runner", "controller", "socket-proxy", "orchestrator"):
        if role not in config["services"]:
            continue
        try:
            probe("docker", "image", "inspect", config["services"][role]["image"])
            ready = True
        except (OSError, KeyError, subprocess.SubprocessError):
            ready = False
        add(
            "service-image:" + role,
            ready,
            (
                "Prepared service image found."
                if ready
                else "Service image is unavailable."
            ),
            (
                "Pull the CPU release images or build the selected Compose services; this check does neither."
                if not ready
                else ""
            ),
        )
    for model in selected:
        try:
            probe("docker", "image", "inspect", policy.models[model]["image"])
            ready = True
        except (OSError, subprocess.SubprocessError):
            ready = False
        add(
            "engine-image:" + model,
            ready,
            (
                "Prepared engine image found."
                if ready
                else "Prepared engine image is unavailable."
            ),
            (
                "Run prepare_engines.py for the selected engine; this check never pulls or builds images."
                if not ready
                else ""
            ),
        )
    names = set()
    for value in config.get("volumes", {}).values():
        if not isinstance(value, dict) or value.get("external") is not True:
            add(
                "external-volumes",
                False,
                "Compose state/cache volumes must remain external.",
                "Use the existing persistent-volume Compose definitions.",
            )
            continue
        names.add(value["name"])
    for model in selected:
        names.update(
            mount["Source"]
            for mount in policy.payloads[model]["HostConfig"]["Mounts"]
            if mount["Type"] == "volume"
        )
    environment = controller.get("environment", {})
    cache_name = environment.get("HF_CACHE_VOLUME", "livepeer-video-hf-cache")
    models_name = environment.get("MODELS_VOLUME", "livepeer-video-model-weights")
    if policy.gpu:
        names.update((cache_name, models_name))
    volumes = {}
    for name in sorted(names):
        try:
            actual = json.loads(probe("docker", "volume", "inspect", name))[0]
            if actual["Name"] != name:
                raise ValueError("volume identity differs")
            volumes[name] = actual
            ready = True
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            ready = False
        add(
            "volume:" + name,
            ready,
            (
                "External volume found."
                if ready
                else "Required external volume is unavailable."
            ),
            (
                "Initialize the intended external volumes before preparing assets."
                if not ready
                else ""
            ),
        )
    manifest = (
        manifest
        if manifest is not None
        else json.loads((ROOT / "configs/model-assets.json").read_text())
    )
    for model in selected:
        matches = [
            (engine, name, spec)
            for engine, entries in manifest["models"].items()
            for name, spec in entries.items()
            if model == engine + "-" + name
            or (model == name and PurePosixPath(public_target).stem in {engine, "all"})
        ]
        if not policy.gpu and not matches:
            add(
                "assets:" + model,
                True,
                "CPU fixture has no GPU asset plan; no inference claim is made.",
            )
            continue
        if len(matches) != 1:
            add(
                "assets:" + model,
                False,
                "No unambiguous pinned asset plan matches the selected model.",
                "Provide --assets-manifest for custom profiles with matching per-engine IDs.",
            )
            continue
        try:
            cache = Path(volumes[cache_name]["Mountpoint"])
            model_root = Path(volumes[models_name]["Mountpoint"])
            engine, name, spec = matches[0]
            assets = check_assets(engine, name, spec, cache, model_root)
            ready = assets["ready"]
            detail = (
                "Prepared file inventory and pinned plan match."
                if ready
                else "; ".join(assets["missing"])
            )
        except (OSError, ValueError, KeyError, TypeError):
            ready, detail = False, "Asset volume data is not readable on this host."
        add(
            "assets:" + model,
            ready,
            detail,
            (
                "Run prepare_weights.py --check in the CPU model-tools container, or run this check on the Docker host with read access to the existing volume data."
                if not ready
                else ""
            ),
        )
    return result()
