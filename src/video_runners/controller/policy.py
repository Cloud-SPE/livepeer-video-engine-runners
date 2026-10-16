"""Trusted engine launch templates and inspected-container verification."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any
from video_runners.catalog import MODEL_ID
from video_runners.contracts import EngineError

OWNER = "io.livepeer.video.owner"
MODEL = "io.livepeer.video.model"
FINGERPRINT = "io.livepeer.video.spec"
IDENTIFIER = re.compile(r"[a-zA-Z0-9_.-]{1,64}")
DIGEST = re.compile(r"(?:[^\s]+@)?sha256:[a-f0-9]{64}")
CONTAINER_ID = re.compile(r"[a-f0-9]{64}")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Policy:
    """Templates come only from the operator's read-only configuration."""

    def __init__(self, config: dict) -> None:
        allowed = {"namespace", "network", "gpu", "models", "allow_local_images"}
        if set(config) - allowed:
            raise ValueError("unknown controller configuration fields")
        self.namespace = config["namespace"]
        self.network = config["network"]
        if not IDENTIFIER.fullmatch(self.namespace) or not IDENTIFIER.fullmatch(
            self.network
        ):
            raise ValueError("invalid namespace or network")
        if self.network in {"host", "bridge", "none"}:
            raise ValueError("a dedicated engine network is required")
        self.gpu = config.get("gpu") or None
        if config.get("gpu") == "" and not config.get("allow_local_images"):
            raise ValueError("ENGINE_GPU_UUID must identify the reserved GPU")
        if self.gpu and not re.fullmatch(r"GPU-[a-zA-Z0-9-]+", self.gpu):
            raise ValueError("gpu must be a GPU UUID, not an index or 'all'")
        self.alias = self.namespace + "-engine"
        self.models = config["models"]
        if not self.models:
            raise ValueError("controller catalog is empty")
        self.payloads: dict[str, dict] = {}
        for name, model in self.models.items():
            if not MODEL_ID.fullmatch(name):
                raise ValueError("invalid model id")
            if set(model) - {
                "image",
                "command",
                "port",
                "health_path",
                "timeout",
                "env",
                "mounts",
                "shm_size",
                "memory",
                "user",
            }:
                raise ValueError("unknown model configuration fields")
            image = model["image"]
            if not DIGEST.fullmatch(image) and not (
                config.get("allow_local_images") is True and not self.gpu
            ):
                raise ValueError(
                    "engine images must be pinned by digest (local CPU tests may opt out)"
                )
            command = model["command"]
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(x, str) for x in command)
            ):
                raise ValueError("command must be an argument vector")
            port = model.get("port", 9100)
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("invalid engine port")
            model["port"] = port
            timeout = model.get("timeout", 1800)
            if type(timeout) not in {int, float} or not 0 < timeout <= 7200:
                raise ValueError("invalid startup timeout")
            path = model.get("health_path", "/health")
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or path.startswith("//")
            ):
                raise ValueError("invalid health path")
            mounts = []
            for mount in model.get("mounts", []):
                if set(mount) - {"source", "target", "read_only", "type"} or not {
                    "source",
                    "target",
                    "read_only",
                } <= set(mount):
                    raise ValueError("mount requires source, target and read_only")
                kind = mount.get("type", "bind")
                if kind not in {"bind", "volume"}:
                    raise ValueError(
                        "only fixed bind mounts or named volumes are allowed"
                    )
                for key in ("source", "target") if kind == "bind" else ("target",):
                    path = PurePosixPath(mount[key])
                    if not path.is_absolute() or str(path) == "/" or ".." in path.parts:
                        raise ValueError(
                            "mount paths must be fixed absolute non-root paths"
                        )
                if kind == "volume" and not re.fullmatch(
                    r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}", mount["source"]
                ):
                    raise ValueError("invalid external volume name")
                if type(mount["read_only"]) is not bool:
                    raise ValueError("read_only must be boolean")
                mounts.append(
                    {
                        "Type": kind,
                        "Source": mount["source"],
                        "Target": mount["target"],
                        "ReadOnly": mount["read_only"],
                    }
                )
            env = model.get("env", {})
            if not isinstance(env, dict) or not all(
                isinstance(k, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)
                and isinstance(v, str)
                for k, v in env.items()
            ):
                raise ValueError("invalid engine environment")
            host = {
                "NetworkMode": self.network,
                "RestartPolicy": {"Name": "no"},
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 1024,
                "ShmSize": model.get("shm_size", 1 << 30),
                "Mounts": mounts,
            }
            if model.get("memory"):
                host["Memory"] = model["memory"]
            if self.gpu:
                host["DeviceRequests"] = [
                    {
                        "Driver": "nvidia",
                        "DeviceIDs": [self.gpu],
                        "Capabilities": [["gpu"]],
                    }
                ]
            payload = {
                "Image": image,
                "Entrypoint": [],
                "Cmd": command,
                "Env": [f"{k}={v}" for k, v in sorted(env.items())],
                "User": model.get("user", "0:0"),
                "HostConfig": host,
                "NetworkingConfig": {
                    "EndpointsConfig": {self.network: {"Aliases": [self.alias]}}
                },
            }
            payload["Labels"] = {
                OWNER: self.namespace,
                MODEL: name,
                FINGERPRINT: fingerprint(payload),
            }
            self.payloads[name] = payload

    def endpoint(self, model: str) -> str:
        return f"http://{self.alias}:{self.models[model]['port']}"

    def verify(self, model: str, actual: dict) -> None:
        expected = self.payloads[model]
        config, host = actual["Config"], actual["HostConfig"]
        for key in ("Image", "Cmd", "User"):
            if config.get(key) != expected[key]:
                raise EngineError(
                    "managed container configuration differs from trusted catalog"
                )
        if config.get("Entrypoint") not in (None, []):
            raise EngineError("unexpected container entrypoint")
        if any(
            config.get("Labels", {}).get(k) != v for k, v in expected["Labels"].items()
        ):
            raise EngineError("managed container labels differ")
        if not set(expected["Env"]).issubset(config.get("Env") or []):
            raise EngineError("managed container environment differs")
        for key in ("NetworkMode", "CapDrop", "PidsLimit", "ShmSize"):
            if host.get(key) != expected["HostConfig"][key]:
                raise EngineError("managed container host configuration differs")

        def mounts(values):
            return [
                {
                    k: m.get(k, False if k == "ReadOnly" else None)
                    for k in ("Type", "Source", "Target", "ReadOnly")
                }
                for m in values
            ]

        def devices(values):
            return [
                {k: m.get(k) for k in ("Driver", "DeviceIDs", "Capabilities")}
                for m in values
            ]

        if mounts(host.get("Mounts") or []) != mounts(expected["HostConfig"]["Mounts"]):
            raise EngineError("managed container mounts differ")
        if devices(host.get("DeviceRequests") or []) != devices(
            expected["HostConfig"].get("DeviceRequests", [])
        ):
            raise EngineError("managed container GPU differs")
        if host.get("Memory", 0) != expected["HostConfig"].get("Memory", 0):
            raise EngineError("managed container memory limit differs")
        if host.get("RestartPolicy", {}).get("Name") != "no":
            raise EngineError("managed container restart policy differs")
        if host.get("Privileged") or any(
            host.get(k)
            for k in (
                "Binds",
                "CapAdd",
                "Devices",
                "VolumesFrom",
                "PortBindings",
                "PidMode",
            )
        ):
            raise EngineError("unexpected privileged container settings")
        if not any(
            x in {"no-new-privileges", "no-new-privileges:true"}
            for x in host.get("SecurityOpt", [])
        ):
            raise EngineError("no-new-privileges is required")
        if set(actual.get("NetworkSettings", {}).get("Networks", {})) != {self.network}:
            raise EngineError("unexpected container network attachment")
