#!/usr/bin/env python3
"""Stage pinned model assets in the persistent external Docker volumes."""

import argparse
import json
from pathlib import Path
import os
import tempfile


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
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    model = args.model or manifest["defaults"][args.engine]
    if model not in manifest["models"][args.engine]:
        parser.error("unknown model for this engine")
    spec = manifest["models"][args.engine][model]
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
    receipt = {
        "engine": args.engine,
        "model": model,
        "revision": spec["revision"],
        "repo": spec["repo"],
        "location": location,
        "ready": not missing,
        "missing": missing,
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
