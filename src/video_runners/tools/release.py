#!/usr/bin/env python3
"""Plan, publish or pull a pinned operator release without GPU or payer access."""

import hashlib
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def plan(root, registry, namespace, tag, revision):
    if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]{1,5})?", registry):
        raise ValueError("registry must be a hostname, without a URL or credentials")
    if not re.fullmatch(
        r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*", namespace
    ):
        raise ValueError("invalid repository namespace")
    if (
        not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag)
        or tag.lower() == "latest"
    ):
        raise ValueError("use an explicit version or source tag, never latest")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source revision must be a full commit")
    node_sources = [
        re.search(r"LIVEPEER_NODE_SOURCE:-([^}]+)", (root / file).read_text())[1]
        for file in ("compose.dev.yml", "deploy/compose/signer.yml")
    ]
    if len(set(node_sources)) != 1 or not re.fullmatch(
        r"https://github.com/livepeer/node.git#[0-9a-f]{40}", node_sources[0]
    ):
        raise ValueError("node roles must use the same pinned source")
    components = {}
    for name in ("runner", "controller", "model-tools", "node", "lightx2v-engine"):
        components[name] = {
            "tag": f"{registry}/{namespace}/{'livepeer-node' if name == 'node' else 'livepeer-video-' + name}:{tag}",
            "context": node_sources[0] if name == "node" else ".",
            "dockerfile": (
                "docker/Dockerfile"
                if name == "node"
                else (
                    "deploy/docker/lightx2v-engine.Dockerfile"
                    if name == "lightx2v-engine"
                    else "deploy/docker/cpu.Dockerfile"
                )
            ),
        }
        if name in {"runner", "controller", "model-tools"}:
            components[name]["target"] = name
    inputs = [
        "uv.lock",
        "configs/model-assets.json",
        "configs/engine-images.json",
        "compose.prod.yml",
        "compose.dev.yml",
        "deploy/compose/signer.yml",
    ]
    inputs += sorted(
        str(file.relative_to(root))
        for pattern in (
            "models/*.json",
            "configs/controller/*.json",
            "configs/lightx2v/*.json",
        )
        for file in root.glob(pattern)
    )
    inputs += sorted(
        {
            value["dockerfile"]
            for value in components.values()
            if value["context"] == "."
        }
    )
    return {
        "schema_version": 1,
        "source_revision": revision,
        "tag": tag,
        "platform": "linux/amd64",
        "components": components,
        "engine_inputs": json.loads((root / "configs/engine-images.json").read_text()),
        "input_sha256": {
            file: hashlib.sha256((root / file).read_bytes()).hexdigest()
            for file in inputs
        },
    }


def publish(root, planned, output, docker):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {**planned, "status": "building", "images": {}}
    save(output / "manifest.json", manifest)
    try:
        for name, component in planned["components"].items():
            print(f"Building {name}", flush=True)
            args = [
                "buildx",
                "build",
                "--builder",
                os.environ.get("RELEASE_BUILDER", "default"),
                "--load",
                "--platform",
                planned["platform"],
                "--file",
                component["dockerfile"],
                "--tag",
                component["tag"],
            ]
            if "target" in component:
                args += ["--target", component["target"]]
            revision = planned["source_revision"]
            source = "https://github.com/Cloud-SPE/livepeer-video-engine-runners"
            if name == "node":
                revision = component["context"].rsplit("#", 1)[1]
                source = "https://github.com/livepeer/node"
            args += [
                "--label",
                "org.opencontainers.image.revision=" + revision,
                "--label",
                "org.opencontainers.image.source=" + source,
                "--label",
                "org.opencontainers.image.version=" + planned["tag"],
            ]
            if name == "lightx2v-engine":
                args += [
                    "--build-arg",
                    "LIGHTX2V_IMAGE=" + planned["engine_inputs"]["lightx2v_base"],
                    "--build-arg",
                    "LIGHTX2V_COMMIT=" + planned["engine_inputs"]["lightx2v_commit"],
                ]
            docker(*args, component["context"])
            if name != "lightx2v-engine":
                # CLI/import check only. Never launch an orchestrator, signer,
                # GPU engine or model download as part of publishing.
                docker(
                    "run",
                    "--rm",
                    "--runtime=runc",
                    "--network=none",
                    component["tag"],
                    "--help",
                )
            docker("push", component["tag"])
            repository = component["tag"].rsplit(":", 1)[0]
            digests = json.loads(
                docker(
                    "image",
                    "inspect",
                    "--format",
                    "{{json .RepoDigests}}",
                    component["tag"],
                    capture=True,
                )
            )
            matches = [
                value
                for value in digests
                if re.fullmatch(re.escape(repository) + r"@sha256:[0-9a-f]{64}", value)
            ]
            if len(matches) != 1:
                raise ValueError("pushed image has no unambiguous registry digest")
            manifest["images"][name] = matches[0]
            save(output / "manifest.json", manifest)
        env = deployment_env(manifest)
        (output / "release.env").write_text(env)
        (output / "release.env").chmod(0o600)
        manifest["status"] = "published"
    except BaseException as exc:
        manifest.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        save(output / "manifest.json", manifest)
    return manifest


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def deployment_env(manifest):
    keys = {
        "runner": "RUNNER_IMAGE",
        "controller": "CONTROLLER_IMAGE",
        "node": "LIVEPEER_NODE_IMAGE",
        "model-tools": "MODEL_TOOLS_IMAGE",
        "lightx2v-engine": "LIGHTX2V_ENGINE_IMAGE",
    }
    if set(manifest.get("images", {})) != set(keys):
        raise ValueError("release requires every role's registry digest")
    values = {key: manifest["images"][name] for name, key in keys.items()}
    values.update(
        SGLANG_ENGINE_IMAGE=manifest["engine_inputs"]["sglang"],
        VLLM_OMNI_ENGINE_IMAGE=manifest["engine_inputs"]["vllm-omni"],
    )
    if any(
        not isinstance(value, str)
        or not re.fullmatch(
            r"[a-z0-9][a-z0-9.-]*(?::[0-9]+)?(?:/[a-z0-9][a-z0-9._-]*)+@sha256:[0-9a-f]{64}",
            value,
        )
        for value in values.values()
    ):
        raise ValueError(
            "release images must be credential-free registry digest references"
        )
    return (
        "# Immutable release references; no credentials or model weights.\n"
        + "".join(f"{key}={value}\n" for key, value in sorted(values.items()))
    )


def pull(root, manifest, env_file, docker):
    if manifest.get("schema_version") != 1 or manifest.get("status") != "published":
        raise ValueError("a complete published release manifest is required")
    env = deployment_env(manifest)
    if manifest["engine_inputs"] != json.loads(
        (root / "configs/engine-images.json").read_text()
    ):
        raise ValueError("checkout engine pins differ from release")
    # Use the checkout's known input paths, never paths supplied by a manifest.
    expected = plan(
        root, "registry.example.com", "release", "check", manifest["source_revision"]
    )["input_sha256"]
    if expected != manifest["input_sha256"]:
        raise ValueError("checkout launch/build inputs differ from release")
    if env_file.exists():
        raise ValueError("refusing to replace an existing env file")
    for image in [
        *manifest["images"].values(),
        manifest["engine_inputs"]["sglang"],
        manifest["engine_inputs"]["vllm-omni"],
    ]:
        docker("pull", image)
    with env_file.open("x") as stream:
        stream.write(env)
    env_file.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "publish"):
        sub = commands.add_parser(command)
        sub.add_argument("--registry", required=True)
        sub.add_argument("--namespace", required=True)
        sub.add_argument("--tag", required=True)
        if command == "publish":
            sub.add_argument("--output", type=Path, required=True)
    consumer = commands.add_parser("pull")
    consumer.add_argument("--manifest", type=Path, required=True)
    consumer.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]

    def git(*arguments):
        return subprocess.check_output(
            ["git", "-C", str(root), *arguments], text=True
        ).strip()

    def docker(*arguments, capture=False):
        result = subprocess.run(
            ["docker", *arguments],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
        )
        return result.stdout.strip() if capture else ""

    revision = git("rev-parse", "HEAD")
    if args.command != "plan" and git(
        "status", "--porcelain", "--untracked-files=normal"
    ):
        parser.error(
            "publish/pull requires a clean source checkout; keep private settings under ignored paths"
        )
    if args.command == "pull":
        manifest = json.loads(args.manifest.read_text())
        if manifest.get("source_revision") != revision:
            parser.error("check out the release's source_revision before pulling")
        pull(root, manifest, args.env_file, docker)
    else:
        planned = plan(root, args.registry, args.namespace, args.tag, revision)
        if args.command == "plan":
            print(json.dumps(planned, indent=2))
        else:
            publish(root, planned, args.output, docker)


if __name__ == "__main__":
    main()
