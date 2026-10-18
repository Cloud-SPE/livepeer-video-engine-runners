#!/usr/bin/env python3
"""Run isolated CPU Docker fixtures, or reconcile a recorded run's cleanup."""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from video_runners.controller.policy import OWNER, Policy, fingerprint
from video_runners.tools.evidence import HostLease, RunReceipt, atomic_json
from video_runners.tools.init_deployment import choose_subnets

ROOT = Path(__file__).resolve().parents[3]
LABEL = "io.livepeer.video.test"
RUN_ID = re.compile(r"vr-[0-9a-f]{10}-[0-9a-f]{12}")


class Docker:
    def call(self, *args):
        return subprocess.check_output(
            ["docker", *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def inspect(self, kind, identifier):
        try:
            return json.loads(self.call(kind, "inspect", identifier))[0]
        except subprocess.CalledProcessError as exc:
            if any(
                message in exc.stderr.lower() for message in ("no such", "not found")
            ):
                return None
            raise

    def ids(self, kind, label):
        arguments = (
            ["ps", "-aq", "--no-trunc"] if kind == "container" else [kind, "ls", "-q"]
        )
        return self.call(*arguments, "--filter", "label=" + label).split()


def resource(kind, actual, role=""):
    if kind == "container":
        value = {
            key: actual[key]
            for key in ("Config", "HostConfig", "Mounts", "Image", "Name")
        }
        # Docker inspection may reorder mounts. Preserve every mount field while
        # comparing their configuration independently of response order.
        value["Mounts"] = sorted(actual["Mounts"], key=fingerprint)
        value["networks"] = sorted(actual["NetworkSettings"]["Networks"])
    elif kind == "network":
        value = {
            key: actual[key] for key in ("Name", "Labels", "IPAM", "Internal", "Driver")
        }
    elif kind == "volume":
        value = {
            key: actual.get(key) for key in ("Name", "Labels", "Driver", "Options")
        }
    else:
        value = {"Id": actual["Id"], "Labels": actual["Config"].get("Labels")}
    return {
        "kind": kind,
        "id": actual.get("Id", actual.get("Name")),
        "role": role,
        "fingerprint": fingerprint(value),
    }


def save_manifest(path, manifest):
    atomic_json(path, manifest)


def capture(path: Path, docker: Docker) -> dict:
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or any(
        item["kind"] not in {"container", "network", "volume", "image"}
        for item in manifest["resources"]
    ):
        raise RuntimeError("unsupported cleanup manifest schema")
    project = manifest["run_id"]
    if (
        not RUN_ID.fullmatch(project)
        or docker.call("info", "--format", "{{.ID}}") != manifest["daemon_id"]
    ):
        raise RuntimeError("cleanup manifest run or Docker daemon differs")
    records = {
        entry["role"] if entry["kind"] == "image" else entry["id"]: entry
        for entry in manifest["resources"]
    }
    for tag in manifest["image_tags"].values():
        actual = docker.inspect("image", tag)
        if actual:
            if (actual["Config"].get("Labels") or {}).get(LABEL) != project:
                raise RuntimeError("test image identity differs")
            item = resource("image", actual, tag)
            if tag in records and records[tag] != item:
                raise RuntimeError("recorded test image was retagged")
            # Key tags independently even if Docker deduplicates an image.
            records[tag] = item
    expected_images = {}
    for service, reference in manifest["service_images"].items():
        image = docker.inspect("image", reference)
        if image:
            expected_images[service] = image["Id"]
    controller = None
    for identifier in docker.ids("container", "com.docker.compose.project=" + project):
        actual = docker.inspect("container", identifier)
        labels = actual["Config"]["Labels"]
        # Compose build labels are inherited by controller-created engines.
        # Classify those through durable controller ownership below instead.
        if labels.get(OWNER) == project:
            continue
        service = labels.get("com.docker.compose.service")
        if (
            labels.get(LABEL) != project
            or service not in expected_images
            or actual["Image"] != expected_images[service]
            or actual["Name"] != f"/{project}-{service}-1"
        ):
            raise RuntimeError(
                "Compose resource does not match this test's image/name/labels"
            )
        previous = records.get(actual["Id"])
        item = resource("container", actual, service)
        if previous and previous != item:
            raise RuntimeError("recorded container configuration drifted")
        records[actual["Id"]] = item
        if service == "controller" and actual["State"]["Running"]:
            controller = actual["Id"]
    manifest["resources"] = list(records.values())
    save_manifest(path, manifest)
    candidates = set(docker.ids("container", OWNER + "=" + project))
    if candidates:
        if not controller:
            raise RuntimeError(
                "managed engines remain but durable ownership cannot be read; retain resources for review"
            )
        state = json.loads(
            docker.call(
                "exec",
                controller,
                "python",
                "-c",
                "import json; print(open('/state/state.json').read())",
            )
        )
        if state["namespace"] != project or candidates - set(state["containers"]):
            raise RuntimeError("unrecorded engine claims this test namespace")
        policy = Policy(deepcopy(manifest["engine_policy"]))
        for identifier in candidates:
            actual = docker.inspect("container", identifier)
            policy.verify(state["containers"][identifier], actual)
            if actual["Image"] != expected_images["engine-image"]:
                raise RuntimeError("managed test engine image differs")
            records[actual["Id"]] = resource("container", actual, "managed-engine")
    manifest["resources"] = list(records.values())
    save_manifest(path, manifest)
    return manifest


def cleanup_manifest(path: Path, docker: Docker):
    manifest = capture(path, docker)
    project = manifest["run_id"]
    if (path.parent / ".private").is_symlink():
        raise RuntimeError("private input directory changed")

    def verified(item):
        identifier = item["role"] if item["kind"] == "image" else item["id"]
        actual = docker.inspect(item["kind"], identifier)
        if actual and resource(item["kind"], actual, item["role"]) != item:
            raise RuntimeError("recorded resource identity/configuration drifted")
        return actual

    def validate(item):
        identifier = item["role"] if item["kind"] == "image" else item["id"]
        actual = verified(item)
        if actual:
            kind = item["kind"]
            labels = (
                actual["Config"].get("Labels", {})
                if kind in {"container", "image"}
                else actual.get("Labels", {})
            )
            if kind == "container":
                managed = (
                    item["role"] == "managed-engine"
                    and labels.get(OWNER) == project
                    and actual["Name"].startswith("/" + project + "-")
                )
                composed = (
                    labels.get(LABEL) == project
                    and actual["Name"] == f"/{project}-{item['role']}-1"
                )
                if not (managed or composed):
                    raise RuntimeError("refusing foreign container")
            elif labels.get(LABEL) != project:
                raise RuntimeError("refusing foreign resource")
            if kind == "volume" and not identifier.startswith(project + "-"):
                raise RuntimeError("refusing persistent or foreign volume")
            if kind == "network" and actual["Name"] not in {
                project + suffix
                for suffix in ("_default", "_control", "-engine", "_docker-api")
            }:
                raise RuntimeError("refusing foreign network")
            if kind == "image" and (
                identifier not in manifest["image_tags"].values()
                or not identifier.startswith("livepeer-video-test-" + project + ":")
            ):
                raise RuntimeError("refusing foreign image")

    # Validate all recorded identities before the first destructive operation.
    for item in manifest["resources"]:
        validate(item)

    def remove_container(item):
        actual = verified(item)
        if actual:
            if item["role"] == "controller" and actual["State"]["Running"]:
                state = json.loads(
                    docker.call(
                        "exec",
                        item["id"],
                        "python",
                        "-c",
                        "print(open('/state/state.json').read())",
                    )
                )
                operations = list(state.get("operations", {}).values())
                if (
                    state["namespace"] != project
                    or any(op.get("state") == "running" for op in operations)
                    or (operations and operations[-1].get("state") != "succeeded")
                ):
                    raise RuntimeError(
                        "controller has unresolved mutations; retain state for review"
                    )
            if actual["State"]["Running"]:
                grace = max(
                    150 if item["role"] == "runner" else 45,
                    actual["Config"].get("StopTimeout") or 0,
                )
                docker.call("stop", "-t", str(grace), item["id"])
            if verified(item):
                docker.call("rm", item["id"])

    # Keep the controller alive while the runner drains and deactivates. Re-read
    # its durable ownership afterwards: a launch may have completed meanwhile.
    for item in manifest["resources"]:
        if item["kind"] == "container" and item["role"] == "runner":
            remove_container(item)
    manifest = capture(path, docker)
    for item in manifest["resources"]:
        validate(item)
    containers = sorted(
        (
            r
            for r in manifest["resources"]
            if r["kind"] == "container" and r["role"] != "runner"
        ),
        key=lambda r: {"managed-engine": 0, "controller": 1}.get(r["role"], 2),
    )
    for item in containers:
        remove_container(item)

    def require_no_containers():
        if (
            docker.ids("container", LABEL + "=" + project)
            or docker.ids("container", "com.docker.compose.project=" + project)
            or docker.ids("container", OWNER + "=" + project)
        ):
            raise RuntimeError("unrecorded resources remain; retain state for review")

    # A timed-out daemon mutation may finish during container teardown. Keep
    # networks, images and durable ownership available until absence is checked.
    require_no_containers()
    for kind in ("network", "volume", "image"):
        for item in manifest["resources"]:
            if item["kind"] != kind:
                continue
            identifier = item["role"] if kind == "image" else item["id"]
            actual = verified(item)
            if actual:
                require_no_containers()
                if kind == "volume" and (
                    not identifier.startswith(project + "-")
                    or (actual.get("Labels") or {}).get(LABEL) != project
                ):
                    raise RuntimeError("refusing persistent or foreign volume")
                docker.call(kind, "rm", identifier)
    if any(
        docker.ids(kind, LABEL + "=" + project)
        for kind in ("container", "network", "volume")
    ) or docker.ids("container", OWNER + "=" + project):
        raise RuntimeError("unrecorded resources remain; retain manifest for review")
    manifest["cleanup"] = "complete"
    save_manifest(path, manifest)
    receipt_path = path.parent / "receipt.json"
    if receipt_path.is_file() and not receipt_path.is_symlink():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("run_id") == project and receipt.get("schema_version") == 1:
            receipt["cleanup"] = "complete"
            atomic_json(receipt_path, receipt)
    private = path.parent / ".private"
    # Remove only named private inputs. Evidence and the cleanup manifest stay.
    for name in ("env", "compose.json", "controller.json"):
        file = private / name
        if file.is_file() and not file.is_symlink():
            file.unlink()


class CPUHarness:
    def __init__(self, receipt: RunReceipt, mode: str, engine: str, docker=None):
        self.receipt, self.mode, self.engine = receipt, mode, engine
        self.docker = docker or Docker()
        self.private = receipt.directory / ".private"
        self.private.mkdir(mode=0o700)
        self.path = receipt.directory / "resources.json"
        roles = ["runner", "orchestrator"] + (
            ["controller", "engine-image"] if mode == "managed" else []
        )
        images = {role: f"livepeer-video-test-{receipt.id}:{role}" for role in roles}
        self.manifest = {
            "schema_version": 1,
            "run_id": receipt.id,
            "daemon_id": self.docker.call("info", "--format", "{{.ID}}"),
            "image_tags": images,
            "service_images": dict(images),
            "resources": [],
            "cleanup": "pending",
        }
        if mode == "managed":
            source = (ROOT / "compose.dev.yml").read_text()
            self.manifest["service_images"]["socket-proxy"] = re.search(
                r"image: (ghcr.io/tecnativa/docker-socket-proxy@sha256:[0-9a-f]{64})",
                source,
            )[1]
        save_manifest(self.path, self.manifest)
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k
            in {
                "PATH",
                "HOME",
                "XDG_RUNTIME_DIR",
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "DOCKER_CONFIG",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
                "DOCKER_API_VERSION",
                "BUILDX_BUILDER",
                "SSH_AUTH_SOCK",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "NO_PROXY",
            }
        }
        self.env.setdefault("BUILDX_BUILDER", "default")
        self.ports = []

    def remember(self, kind, actual):
        self.manifest["resources"].append(resource(kind, actual))
        save_manifest(self.path, self.manifest)

    def prepare(self):
        public = json.loads((ROOT / f"models/{self.engine}.json").read_text())
        models = public["models"]
        project = self.receipt.id
        values = {
            "COMPOSE_PROJECT_NAME": project,
            "ENGINE_NAMESPACE": project,
            "ENGINE_NETWORK": project + "-engine",
            "ENGINE": self.engine,
            "MODEL": "",
            "CONTROLLER_STATE_VOLUME": project + "-state",
            "GPU_LEASE_VOLUME": project + "-leases",
            "E2E_MODEL_ONE": models[0]["id"],
            "E2E_MODEL_TWO": models[1]["id"],
            "BOOTSTRAP_SECRET": os.urandom(32).hex(),
            "RUNNER_ADMIN_TOKEN": os.urandom(32).hex(),
            "ENGINE_CONTROLLER_TOKEN": os.urandom(32).hex(),
            "ENGINE_CONTROLLER_CATALOG": str(self.private / "controller.json"),
            "CPU_ARTIFACT_DIR": str(self.receipt.directory / "videos"),
        }
        self.receipt.data["inputs"] = {
            "mode": self.mode,
            "catalog": self.engine,
            "models": [m["id"] for m in models],
            "workload": "CPU stub; both delivery modes and model switching",
        }
        self.receipt.save()
        # The setup lease excludes subnet/port allocation by other harness runs.
        # Reserve networks immediately and keep port sockets open during builds.
        with HostLease("cpu-setup", inherited=False, wait=True):
            prefixes = choose_subnets()
            for index, key in enumerate(
                (
                    "SUBNET_PREFIX",
                    "CONTROL_SUBNET_PREFIX",
                    "ENGINE_SUBNET_PREFIX",
                    "DOCKER_API_SUBNET_PREFIX",
                )
            ):
                values[key] = prefixes[index]
            names = ["default"] + (
                ["control", "engine", "docker-api"] if self.mode == "managed" else []
            )
            for name in names:
                key = {
                    "default": "SUBNET_PREFIX",
                    "control": "CONTROL_SUBNET_PREFIX",
                    "engine": "ENGINE_SUBNET_PREFIX",
                    "docker-api": "DOCKER_API_SUBNET_PREFIX",
                }[name]
                network_name = project + ("-engine" if name == "engine" else "_" + name)
                args = [
                    "network",
                    "create",
                    "--subnet",
                    values[key] + ".0/24",
                    "--label",
                    LABEL + "=" + project,
                    "--label",
                    "com.docker.compose.project=" + project,
                    "--label",
                    "com.docker.compose.network=" + name,
                ]
                if name in {"control", "docker-api"}:
                    args.append("--internal")
                identifier = self.docker.call(*args, network_name)
                self.remember("network", self.docker.inspect("network", identifier))
            for key in ("ORCHESTRATOR_PORT", "RUNNER_ADMIN_PORT"):
                sock = socket.socket()
                sock.bind(("127.0.0.1", 0))
                self.ports.append(sock)
                values[key] = str(sock.getsockname()[1])
        values["DOCKER_SOCKET_PATH"] = os.environ.get(
            "DOCKER_SOCKET_PATH",
            (
                f"/run/user/{os.getuid()}/docker.sock"
                if "name=rootless"
                in self.docker.call("info", "--format", "{{json .SecurityOptions}}")
                else "/var/run/docker.sock"
            ),
        )
        if self.mode == "managed":
            for suffix in ("state", "leases"):
                name = project + "-" + suffix
                self.docker.call(
                    "volume", "create", "--label", LABEL + "=" + project, name
                )
                self.remember("volume", self.docker.inspect("volume", name))
        else:
            for name, key in (("hf", "HF_CACHE_DIR"), ("models", "MODELS_DIR")):
                path = self.private / name
                path.mkdir()
                values[key] = str(path)
        services = {
            role: {
                "image": tag,
                "labels": {LABEL: project},
                "build": {"labels": {LABEL: project}},
            }
            for role, tag in self.manifest["image_tags"].items()
        }
        if self.mode == "managed":
            services["socket-proxy"] = {"labels": {LABEL: project}}
        else:
            services["runner"]["ipc"] = "private"
        networks = {name: {"labels": {LABEL: project}} for name in names}
        atomic_json(
            self.private / "compose.json", {"services": services, "networks": networks}
        )
        self.values = values
        self.env.update(values)
        self.env.update(
            TEST_ENV_FILE=str(self.private / "env"),
            TEST_COMPOSE_OVERLAY=str(self.private / "compose.json"),
        )
        with (self.private / "env").open("x") as file:
            os.chmod(file.name, 0o600)
            for key, value in values.items():
                file.write(f"{key}={value}\n")

    def compose(self, *args):
        base = (
            "compose.dev.yml"
            if self.mode == "managed"
            else "deploy/compose/bundled.yml"
        )
        return [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(self.private / "env"),
            "-p",
            self.receipt.id,
            "-f",
            str(ROOT / base),
            "-f",
            str(self.private / "compose.json"),
            *args,
        ]

    def command(self, name, args):
        def redacted(content):
            for key, value in self.values.items():
                if value and any(word in key for word in ("TOKEN", "SECRET")):
                    content = content.replace(value, "[redacted]")
            return content

        self.receipt.data["step"] = name
        self.receipt.save()
        with (self.receipt.directory / f"{name}.log").open("w") as output:
            try:
                subprocess.run(
                    args,
                    cwd=ROOT,
                    env=self.env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            except subprocess.CalledProcessError:
                self.receipt.result({"step": name, "status": "failed"})
                output.flush()
                content = redacted(
                    (self.receipt.directory / f"{name}.log").read_text(errors="replace")
                )
                print(
                    f"{name} failed; last 60 log lines:\n"
                    + "\n".join(content.splitlines()[-60:]),
                    file=sys.stderr,
                )
                try:
                    snapshot = capture(self.path, self.docker)
                    for item in snapshot["resources"]:
                        if item["kind"] != "container" or not self.docker.inspect(
                            "container", item["id"]
                        ):
                            continue
                        result = subprocess.run(
                            ["docker", "logs", "--tail", "100", item["id"]],
                            text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            check=True,
                        )
                        content = redacted(result.stdout)
                        (self.receipt.directory / (item["role"] + ".log")).write_text(
                            content
                        )
                except Exception as diagnostic:
                    self.receipt.data["diagnostics_error_type"] = type(
                        diagnostic
                    ).__name__
                    self.receipt.save()
                raise
        self.receipt.result({"step": name, "status": "passed"})

    def run(self):
        try:
            self.prepare()
            self.command("build", self.compose("build", *self.manifest["image_tags"]))
            if self.mode == "managed":
                image = self.docker.inspect(
                    "image", self.manifest["image_tags"]["engine-image"]
                )["Id"]
                models = json.loads((ROOT / f"models/{self.engine}.json").read_text())[
                    "models"
                ]
                policy = dict(
                    namespace=self.receipt.id,
                    network=self.values["ENGINE_NETWORK"],
                    gpu=None,
                    allow_local_images=True,
                    models={
                        m["id"]: dict(
                            image=image,
                            command=[
                                "video-stub-engine",
                                "--api",
                                "lightx2v" if m["engine"] == "lightx2v" else "openai",
                                "--host",
                                "0.0.0.0",
                                "--port",
                                "9100",
                                "--delay",
                                "1",
                            ],
                            timeout=30,
                            user="65532:65532",
                        )
                        for m in models
                    },
                )
                atomic_json(self.private / "controller.json", policy)
                # This CPU fixture contains no credentials. The non-root
                # controller must read its single-file bind mount; the parent
                # directory remains private on the host.
                (self.private / "controller.json").chmod(0o644)
                self.manifest["engine_policy"] = policy
                save_manifest(self.path, self.manifest)
            with HostLease("cpu-setup", inherited=False, wait=True):
                for sock in self.ports:
                    sock.close()
                self.command(
                    "startup",
                    self.compose("up", "-d", "--wait", "--wait-timeout", "180"),
                )
            capture(self.path, self.docker)
            self.env.update(
                ADMIN_URL=f"http://127.0.0.1:{self.values['RUNNER_ADMIN_PORT']}",
                DISCOVERY_URL=f"http://127.0.0.1:{self.values['ORCHESTRATOR_PORT']}/discovery",
            )
            script = "managed-checks.sh" if self.mode == "managed" else "e2e.sh"
            self.command("workload", ["bash", str(ROOT / "tests/e2e" / script)])
            from video_runners.tools.validate_gpu import verify_video

            for path in sorted((self.receipt.directory / "videos").glob("*.mp4")):
                self.receipt.result(
                    {"video": verify_video(path), "backend": "CPU fixture"}
                )
        finally:
            for sock in self.ports:
                sock.close()
            try:
                cleanup_manifest(self.path, self.docker)
                self.receipt.data["cleanup"] = "complete"
            except Exception as exc:
                self.receipt.data["cleanup"] = "review_required"
                self.receipt.data["cleanup_error_type"] = type(exc).__name__
                self.receipt.save()
                raise RuntimeError(f"cleanup needs review: {self.path}") from exc
            self.receipt.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bundled", "managed"), default="managed")
    parser.add_argument(
        "--engine",
        choices=("stub", "sglang", "lightx2v", "vllm-omni", "all"),
        default="stub",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts/cpu-validation"
    )
    parser.add_argument(
        "--cleanup",
        type=Path,
        help="Verify and clean only this run manifest's resources",
    )
    args = parser.parse_args()
    if args.cleanup:
        cleanup_manifest(args.cleanup, Docker())
        return
    if args.mode == "bundled" and args.engine != "stub":
        parser.error("bundled CPU validation uses only the stub catalog")
    with RunReceipt(ROOT, args.output_dir, "cpu-" + args.mode) as receipt:
        print(f"CPU run {receipt.id}; evidence: {receipt.directory}", flush=True)
        CPUHarness(receipt, args.mode, args.engine).run()


if __name__ == "__main__":
    main()
