#!/usr/bin/env python3
"""Stage pinned model assets in the persistent external Docker volumes."""

import argparse
import json
from pathlib import Path, PurePosixPath
import os
import tempfile
import hashlib
import re

WEIGHT_SUFFIXES = {".bin", ".pt", ".pth", ".safetensors"}


def validate_plan(spec):
    def relative(value):
        if not isinstance(value, str) or not value or "\x00" in value:
            return False
        path = PurePosixPath(value)
        return not path.is_absolute() and ".." not in path.parts and str(path) != "."

    try:
        valid = spec["storage"] in {"hf", "models"}
        for asset in [spec, *spec.get("extra_files", [])]:
            valid = (
                valid
                and isinstance(asset["repo"], str)
                and bool(asset["repo"])
                and bool(re.fullmatch(r"[0-9a-f]{40}", asset["revision"]))
            )
        if spec["storage"] == "models":
            valid = valid and relative(spec["directory"])
        valid = valid and all(
            relative(item["filename"]) for item in spec.get("extra_files", [])
        )
        valid = valid and all(relative(name) for name in spec.get("required_files", []))
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError(
            "asset plan requires immutable revisions and volume-relative paths"
        )


def plan_sha256(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def asset_inventory(spec, location, cache_dir, models_dir):
    storage = "hf" if spec["storage"] == "hf" else "models"
    roots = {"hf": cache_dir.resolve(), "models": models_dir.resolve()}
    location = Path(location)
    paths = [
        (storage, p)
        for p in location.rglob("*")
        if ".cache" not in p.relative_to(location).parts and p.is_file()
    ]
    paths += [
        ("models", models_dir / item["filename"])
        for item in spec.get("extra_files", [])
        if (models_dir / item["filename"]).is_file()
    ]
    paths += [
        ("models", models_dir / name)
        for name in spec.get("required_files", [])
        if (models_dir / name).is_file()
    ]
    files = {}
    for storage, path in paths:
        root = roots[storage]
        if not path.resolve().is_relative_to(root):
            raise ValueError("prepared asset escapes its asset volume")
        relative = path.absolute().relative_to(root).as_posix()
        files[storage, relative] = dict(
            storage=storage,
            path=relative,
            size=path.stat().st_size,
        )
    return [files[key] for key in sorted(files)]


def check_assets(engine, model, spec, cache_dir, models_dir):
    try:
        validate_plan(spec)
    except ValueError as exc:
        return {"ready": False, "missing": [str(exc)]}
    receipt = cache_dir / "livepeer-assets" / f"{engine}-{model}.json"
    missing = []
    if not receipt.resolve().is_relative_to(cache_dir.resolve()):
        missing.append("preparation receipt escapes its asset volume")
    elif not receipt.is_file():
        missing.append("preparation receipt is missing")
    else:
        try:
            saved = json.loads(receipt.read_text())
        except (OSError, ValueError):
            saved = {}
        expected = dict(
            engine=engine,
            model=model,
            repo=spec["repo"],
            revision=spec["revision"],
            ready=True,
        )
        if (
            not isinstance(saved, dict)
            or saved.get("ready") is not True
            or any(saved.get(k) != v for k, v in expected.items())
        ):
            missing.append(
                "preparation receipt does not match the selected pinned assets"
            )
        elif not isinstance(saved.get("files"), list) or not saved["files"]:
            missing.append(
                "file inventory is missing; repeat preparation to record cached assets"
            )
        else:
            if saved.get("plan_sha256") != plan_sha256(spec):
                missing.append("preparation plan has changed; repeat preparation")
            roots = {"hf": cache_dir, "models": models_dir}
            for item in saved["files"]:
                if (
                    not isinstance(item, dict)
                    or item.get("storage") not in roots
                    or not isinstance(item.get("path"), str)
                    or type(item.get("size")) is not int
                    or item["size"] < 0
                ):
                    missing.append("file inventory is invalid")
                    continue
                root = roots[item["storage"]].resolve()
                relative = Path(item["path"])
                path = root / relative
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not path.resolve().is_relative_to(root)
                ):
                    missing.append("file inventory escapes its asset volume")
                elif not path.is_file() or path.stat().st_size != item["size"]:
                    missing.append(
                        f"{item['storage']}:{item['path']} is missing or has a different size"
                    )
                elif item["size"] == 0 and path.suffix in WEIGHT_SUFFIXES:
                    missing.append(f"{item['storage']}:{item['path']} is empty")
            if spec["storage"] == "hf":
                ref = (
                    cache_dir
                    / "hub"
                    / ("models--" + spec["repo"].replace("/", "--"))
                    / "refs/main"
                )
                try:
                    current = (
                        ref.read_text().strip()
                        if ref.resolve().is_relative_to(cache_dir.resolve())
                        else ""
                    )
                except OSError:
                    current = ""
                if current != spec["revision"]:
                    missing.append(
                        "offline main ref does not match the pinned revision"
                    )
    return {"ready": not missing, "missing": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=("sglang", "lightx2v", "vllm-omni"))
    parser.add_argument("--model", default="")
    parser.add_argument("--cache-dir", type=Path, default=Path("/cache"))
    parser.add_argument("--models-dir", type=Path, default=Path("/models"))
    parser.add_argument("--manifest", type=Path, default=Path("/app/model-assets.json"))
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the selected pinned assets without downloading",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check saved preparation inventory without downloads or writes",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    model = args.model or manifest["defaults"][args.engine]
    if model not in manifest["models"][args.engine]:
        parser.error("unknown model for this engine")
    spec = manifest["models"][args.engine][model]
    try:
        validate_plan(spec)
    except ValueError as exc:
        parser.error(str(exc))
    if args.check and args.plan:
        parser.error("choose --check or --plan")
    if args.check:
        result = check_assets(args.engine, model, spec, args.cache_dir, args.models_dir)
        print(json.dumps(dict(engine=args.engine, model=model, **result)))
        if not result["ready"]:
            parser.exit(
                1,
                "Assets are not ready; repeat preparation to reuse cached data and record the selected plan.\n",
            )
        return
    if args.plan:
        print(json.dumps({"engine": args.engine, "model": model, **spec}, indent=2))
        return
    from huggingface_hub import hf_hub_download, snapshot_download

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    args.models_dir.mkdir(parents=True, exist_ok=True)
    options = {}
    if "allow_patterns" in spec:
        patterns = spec["allow_patterns"]
        if (
            not isinstance(patterns, list)
            or not patterns
            or not all(isinstance(value, str) and value for value in patterns)
        ):
            parser.error("allow_patterns must be a nonempty list of filename patterns")
        options["allow_patterns"] = patterns
    if spec["storage"] == "hf":
        location = snapshot_download(
            spec["repo"],
            revision=spec["revision"],
            cache_dir=str(args.cache_dir / "hub"),
            **options,
        )
        # Engines resolve the repository's default revision in offline mode.
        # Point that ref to the exact staged revision rather than a moving main.
        refs = (
            args.cache_dir
            / "hub"
            / ("models--" + spec["repo"].replace("/", "--"))
            / "refs"
        )
        refs.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=refs, delete=False) as file:
            file.write(spec["revision"])
            temporary = file.name
        os.replace(temporary, refs / "main")
    else:
        location = snapshot_download(
            spec["repo"],
            revision=spec["revision"],
            local_dir=str(args.models_dir / spec["directory"]),
            **options,
        )
    for extra in spec.get("extra_files", []):
        hf_hub_download(
            extra["repo"],
            filename=extra["filename"],
            revision=extra["revision"],
            local_dir=str(args.models_dir),
        )
    missing = [
        name
        for name in spec.get("required_files", [])
        if not (args.models_dir / name).is_file()
    ]
    files = asset_inventory(spec, location, args.cache_dir, args.models_dir)
    missing.extend(
        f"{item['storage']}:{item['path']} is empty"
        for item in files
        if item["size"] == 0 and Path(item["path"]).suffix in WEIGHT_SUFFIXES
    )
    if not files:
        missing.append("no prepared asset files")
    receipt = {
        "engine": args.engine,
        "model": model,
        "revision": spec["revision"],
        "repo": spec["repo"],
        "location": location,
        "ready": not missing,
        "missing": missing,
        "plan_sha256": plan_sha256(spec),
        "files": files,
    }
    receipts = args.cache_dir / "livepeer-assets"
    receipts.mkdir(exist_ok=True)
    (receipts / f"{args.engine}-{model}.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    print(json.dumps(receipt, indent=2), flush=True)
    if missing:
        parser.exit(
            1,
            "Additional local assets are required; see the model preparation instructions in docs/guides/container-deployment.md.\n",
        )


if __name__ == "__main__":
    main()
