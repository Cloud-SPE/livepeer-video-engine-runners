#!/usr/bin/env python3
"""Check catalog, pin and reference agreement; use --write to refresh generated files."""

import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
ENGINES = ("sglang", "lightx2v", "vllm-omni")
CLI_SOURCES = {
    "python -m video_runners.tools.quality": "tools/quality.py",
    "python -m video_runners.tools.quality_vbench": "tools/quality_vbench.py",
    "video-runner": "runner/app.py",
    "video-controller": "controller/app.py",
    "video-client": "client.py",
    "video-stub-engine": "stub_engine.py",
    "python3 src/video_runners/tools/engine_entrypoint.py": "tools/engine_entrypoint.py",
    **{
        f"python3 src/video_runners/tools/{name}.py": f"tools/{name}.py"
        for name in (
            "init_deployment",
            "prepare_engines",
            "prepare_weights",
            "validate_all",
            "validate_gpu",
            "validate_recovery",
            "sync_config",
            "cpu_harness",
        )
    },
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def interleave(groups: list[list]) -> list:
    """Keep the existing combined order: each engine's first model, then second."""
    return [
        group[index]
        for index in range(max(map(len, groups)))
        for group in groups
        if index < len(group)
    ]


def combined_public(directory: Path) -> dict:
    """Read only public per-engine sources, including their bundled commands."""
    sources = {engine: read_json(directory / f"{engine}.json") for engine in ENGINES}
    groups = [
        [
            dict(deepcopy(model), id=f"{engine}-{model['id']}")
            for model in data["models"]
        ]
        for engine, data in sources.items()
    ]
    first = sources[ENGINES[0]]
    default = first.get("default") or first["models"][0]["id"]
    return {"default": f"{ENGINES[0]}-{default}", "models": interleave(groups)}


def combined_trusted(directory: Path) -> dict:
    """Read only trusted policies. Public catalogs cannot supply launch fields."""
    header = None
    groups = []
    for engine in ENGINES:
        source = read_json(directory / f"{engine}.json")
        current = {key: value for key, value in source.items() if key != "models"}
        if header is not None and current != header:
            raise ValueError(
                f"{directory / (engine + '.json')}: trusted headers disagree"
            )
        header = current
        groups.append(
            [
                (f"{engine}-{name}", deepcopy(model))
                for name, model in source["models"].items()
            ]
        )
    return {**header, "models": dict(interleave(groups))}


def check_sources(root: Path) -> list[str]:
    """Cross-check shipped preparation/launch inputs; never synthesize policy."""
    errors = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    images = read_json(root / "configs/engine-images.json")
    assets = read_json(root / "configs/model-assets.json")
    for key in ("sglang", "vllm-omni", "lightx2v_base"):
        require(
            re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", images[key]) is not None,
            f"configs/engine-images.json: {key} must be pinned by registry digest",
        )
    require(
        re.fullmatch(r"[0-9a-f]{40}", images["lightx2v_commit"]) is not None,
        "configs/engine-images.json: lightx2v_commit must be a full commit",
    )
    require(
        set(assets["models"]) == set(assets["defaults"]) == set(ENGINES),
        "configs/model-assets.json: engine sets disagree with supported sources",
    )
    for engine in ENGINES:
        public = read_json(root / f"models/{engine}.json")
        public_ids = [model["id"] for model in public["models"]]
        trusted = read_json(root / f"configs/controller/{engine}.json")["models"]
        plans = assets["models"][engine]
        require(
            len(set(public_ids)) == len(public_ids)
            and set(public_ids) == set(trusted) == set(plans),
            f"{engine}: public, trusted and asset model IDs must agree without duplicates",
        )
        require(
            public["default"] == assets["defaults"][engine]
            and public["default"] in public_ids,
            f"{engine}: public and asset defaults must agree and name a model",
        )
        for name, model in trusted.items():
            expected = (
                "${LIGHTX2V_ENGINE_IMAGE}" if engine == "lightx2v" else images[engine]
            )
            require(
                model["image"] == expected,
                f"{engine}/{name}: trusted image disagrees with preparation",
            )
            if name not in plans:
                continue
            plan = plans[name]
            for asset in [plan, *plan.get("extra_files", [])]:
                require(
                    re.fullmatch(r"[0-9a-f]{40}", asset["revision"]) is not None,
                    f"{engine}/{name}: asset revisions must be full commits",
                )
            command = model["command"]
            if engine == "lightx2v":
                model_path = "/models/" + plan.get("directory", "")
                flag = "--model_path"
                require(
                    plan["storage"] == "models",
                    f"{engine}/{name}: expected models storage",
                )
            else:
                model_path = plan["repo"]
                flag = "--model-path" if engine == "sglang" else "serve"
                require(
                    plan["storage"] == "hf", f"{engine}/{name}: expected hf storage"
                )
            index = command.index(flag) if flag in command else len(command)
            require(
                index + 1 < len(command) and command[index + 1] == model_path,
                f"{engine}/{name}: trusted model path disagrees with prepared asset",
            )
    # Check only the separate-engine defaults. Legacy bundled base tags remain
    # separately configurable and do not establish pinned-GPU compatibility.
    for engine, file, variable in (
        ("sglang", "external.yml", "EXTERNAL_ENGINE_IMAGE"),
    ):
        text = (root / "deploy/compose" / file).read_text()
        match = re.search(
            r"^\s+image:\s+\$\{" + variable + r":-([^}]+)\}", text, re.MULTILINE
        )
        require(
            match is not None and match[1] == images[engine],
            f"deploy/compose/{file}: {variable} default disagrees with image manifest",
        )
    for file, arguments in (
        (
            "lightx2v-engine.Dockerfile",
            {"LIGHTX2V_IMAGE": "lightx2v_base", "LIGHTX2V_COMMIT": "lightx2v_commit"},
        ),
        ("lightx2v.Dockerfile", {"LIGHTX2V_COMMIT": "lightx2v_commit"}),
    ):
        text = (root / "deploy/docker" / file).read_text()
        for argument, key in arguments.items():
            match = re.search(r"^ARG " + argument + r"=(\S+)$", text, re.MULTILINE)
            require(
                match is not None and match[1] == images[key],
                f"deploy/docker/{file}: {argument} disagrees with image manifest",
            )
    return errors


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Emit the same simple left-aligned tables as the pinned Markdown formatter."""
    widths = [
        max(3, *(len(row[i]) for row in [headers, *rows])) for i in range(len(headers))
    ]

    def line(row):
        return (
            "| "
            + " | ".join(value.ljust(width) for value, width in zip(row, widths))
            + " |"
        )

    return "\n".join([line(headers), line(["-" * n for n in widths]), *map(line, rows)])


def code(value: str) -> str:
    return "`" + value.replace("|", "\\|").replace("\n", " ") + "`"


def trusted_fields(root: Path) -> list[list[str]]:
    """Extract the two literal allowlists from Policy, without importing it."""
    tree = ast.parse((root / "src/video_runners/controller/policy.py").read_text())
    policy = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Policy"
    )
    constructor = next(
        node
        for node in policy.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    fields = {}
    for node in ast.walk(constructor):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "allowed"
            for target in node.targets
        ):
            fields["Top level"] = ast.literal_eval(node.value)
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Sub)
            and ast.unparse(node.left) == "set(model)"
        ):
            fields["Each model"] = ast.literal_eval(node.right)
    if set(fields) != {"Top level", "Each model"}:
        raise ValueError(
            "Policy field allowlists changed shape; update trusted_fields extraction"
        )
    return [
        [scope, ", ".join(map(code, sorted(names)))] for scope, names in fields.items()
    ]


def configuration_reference(root: Path) -> str:
    """Read Python ASTs, never imports, private env values or live services."""
    parts = [
        "# Configuration and CLI reference",
        "Generated by `python3 src/video_runners/tools/sync_config.py --write`. Edit the source, then\n"
        "regenerate; `scripts/check.sh` rejects drift. The [configuration guide](../guides/configuration.md)\n"
        "explains authority and update procedures.",
        "Defaults, types and choices below are Python source expressions, including\n"
        "symbolic constants. No private env file or process environment is read.\n"
        "Omitted argparse defaults are `None`; boolean actions default to `False`.\n"
        "For validation rules and runtime requirements follow the linked source and\n"
        "the deployment guides. Shell wrapper and node configuration are documented\n"
        "in the [container](../guides/container-deployment.md) and [node](../guides/node-deployment.md) guides.",
        "## Public data fields",
        "These are dataclass fields, not a JSON Schema. `ModelSpec.url` is an internal\n"
        "adapter override; the public catalog loader does not load it from JSON.\n"
        "Job request values are parsed after model request defaults are applied.",
    ]
    package = Path("src/video_runners")
    for file, name in (("catalog.py", "ModelSpec"), ("contracts.py", "JobRequest")):
        path = package / file
        tree = ast.parse((root / path).read_text())
        cls = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == name
        )
        rows = [
            [
                code(node.target.id),
                code(ast.unparse(node.annotation)),
                code(ast.unparse(node.value)) if node.value else "Required",
            ]
            for node in cls.body
            if isinstance(node, ast.AnnAssign)
        ]
        parts += [
            f"### {name}",
            f"Source: [{file}](../../{path.as_posix()}).",
            table(["Field", "Type", "Default"], rows),
        ]
    parts += [
        "## Trusted managed policy fields",
        "Accepted keys come from [Policy](../../src/video_runners/controller/policy.py).\n"
        "This list is not a JSON Schema; follow that source for required values,\n"
        "mount fields, limits and verification rules. Public fields do not populate\n"
        "this policy. `allow_local_images` is for CPU fixtures without a GPU.",
        table(["Scope", "Accepted keys"], trusted_fields(root)),
        "## Python commands",
    ]
    for command, file in CLI_SOURCES.items():
        path = package / file
        tree = ast.parse((root / path).read_text())
        rows = []
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "add_argument"
            ):
                continue
            options = [ast.literal_eval(arg) for arg in node.args]
            kwargs = {keyword.arg: keyword.value for keyword in node.keywords}
            action = (
                ast.literal_eval(kwargs["action"]) if "action" in kwargs else "store"
            )
            default = (
                ast.unparse(kwargs["default"])
                if "default" in kwargs
                else ("False" if action == "store_true" else "None")
            )
            nargs = ast.literal_eval(kwargs["nargs"]) if "nargs" in kwargs else None
            required = (
                "required" in kwargs and ast.literal_eval(kwargs["required"])
            ) or (not options[0].startswith("-") and nargs not in ("?", "*"))
            details = ["Required"] if required else []
            if nargs is not None:
                details.append(code(f"nargs={nargs!r}"))
            if action != "store":
                details.append(code(action))
            rows.append(
                [
                    ", ".join(map(code, options)),
                    (
                        code(ast.unparse(kwargs["choices"]))
                        if "choices" in kwargs
                        else "—"
                    ),
                    code(default),
                    "; ".join(details) or "—",
                ]
            )
        parts += [
            f"### {command}",
            f"Source: [{file}](../../{path.as_posix()}).",
            table(["Argument", "Choices", "Default", "Requirement / action"], rows),
        ]
    return "\n\n".join(parts) + "\n"


def generated_files(root: Path) -> dict[Path, str]:
    return {
        Path("models/all.json"): json.dumps(combined_public(root / "models"), indent=2)
        + "\n",
        Path("configs/controller/all.json"): json.dumps(
            combined_trusted(root / "configs/controller"), indent=2
        )
        + "\n",
        Path("docs/reference/configuration.md"): configuration_reference(root),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Refresh generated files after checking source consistency",
    )
    args = parser.parse_args()
    try:
        errors = check_sources(ROOT)
        outputs = generated_files(ROOT)
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        parser.exit(1, f"Configuration check failed: {exc}\n")
    if errors:
        parser.exit(
            1, "\n".join(errors) + "\nFix source disagreement before regeneration.\n"
        )
    stale = []
    for relative, content in outputs.items():
        path = ROOT / relative
        if args.write:
            path.write_text(content)
        elif not path.exists() or path.read_text() != content:
            stale.append(str(relative))
    if stale:
        parser.exit(
            1,
            "Generated files are stale: "
            + ", ".join(stale)
            + "\nRun python3 src/video_runners/tools/sync_config.py --write after reviewing source changes.\n",
        )
    print("Configuration sources and generated files agree.")


if __name__ == "__main__":
    main()
