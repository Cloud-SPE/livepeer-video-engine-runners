"""Run in an isolated, pinned VBench environment against saved clips only.

This standalone evaluator deliberately imports no serving or Livepeer code.
Its model downloads belong in a persistent evaluator cache volume.
"""

import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import hashlib
from importlib import metadata
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import re


@contextmanager
def reserve_gpu(directory, gpu_uuid):
    if not re.fullmatch(r"GPU-[A-Za-z0-9-]+", gpu_uuid):
        raise ValueError("GPU UUID is required")
    path = directory / (gpu_uuid + ".lock")
    # The managed controller initializes this file with its normal ownership.
    # Open the same inode without creating/changing lease files or permissions.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "GPU is leased by another controller or evaluator"
            ) from exc
        yield
    finally:
        os.close(descriptor)


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def package_versions():
    names = {d.metadata["Name"] for d in metadata.distributions()}
    return {name: metadata.version(name) for name in sorted(names)}


def verify_manifest(benchmark, receipt):
    def identity(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def without_id(value):
        return {key: item for key, item in value.items() if key != "id"}

    jobs = benchmark["jobs"]
    ids = {job["id"] for job in jobs}
    if (
        benchmark.get("schema_version") != 1
        or benchmark.get("kind") != "video-quality"
        or benchmark.get("id") != identity(without_id(benchmark))
        or not jobs
        or len(ids) != len(jobs)
        or any(job["id"] != identity(without_id(job))[:24] for job in jobs)
        or receipt.get("plan_id") != benchmark["id"]
        or set(receipt["jobs"]) - ids
    ):
        raise RuntimeError("evaluation plan or receipt identity differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evaluator-ref", required=True)
    parser.add_argument("--dimension", action="append", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--gpu-uuid", default="")
    parser.add_argument("--lease-directory", type=Path)
    args = parser.parse_args()
    if args.device == "cuda":
        if not args.gpu_uuid or args.lease_directory is None:
            parser.error(
                "CUDA evaluation requires the GPU UUID and shared controller lease directory"
            )
        visible = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            text=True,
            timeout=15,
        ).splitlines()
        if visible != [args.gpu_uuid]:
            parser.error("container must expose exactly the leased GPU")
    lease = (
        reserve_gpu(args.lease_directory, args.gpu_uuid)
        if args.device == "cuda"
        else nullcontext()
    )
    with lease:
        run = args.run_dir.resolve()
        args.output = args.output.resolve()
        if not args.output.is_relative_to(run) or args.output.parent == run:
            parser.error("write evaluation results in a new subdirectory of the run")
        owner = run.stat()
        created = []
        for parent in args.output.parents:
            if parent == run or parent.exists():
                break
            created.append(parent)
        try:
            evaluate(args, parser)
        finally:
            # Return only newly generated artifacts to the input run's owner.
            if os.geteuid() == 0 and created:
                for path in list(args.output.parent.rglob("*")) + created:
                    if path.exists() and not path.is_symlink():
                        os.chown(path, owner.st_uid, owner.st_gid)


def evaluate(args, parser):
    spec = find_spec("vbench")
    source = Path(spec.origin).parent.parent if spec else Path("/nonexistent")
    if (source / ".git").is_dir():
        revision = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        subprocess.run(
            ["git", "-C", str(source), "diff", "--quiet", "HEAD"], check=True
        )
    else:
        distribution = metadata.distribution("vbench")
        origin = json.loads(distribution.read_text("direct_url.json") or "{}")
        revision = origin.get("vcs_info", {}).get("commit_id")
    if revision != args.evaluator_ref:
        parser.error("install VBench from the requested immutable Git commit")
    allowed = {
        "subject_consistency",
        "background_consistency",
        "motion_smoothness",
        "dynamic_degree",
        "aesthetic_quality",
        "imaging_quality",
    }
    if (
        not args.dimension
        or set(args.dimension) - allowed
        or len(args.dimension) != len(set(args.dimension))
    ):
        parser.error("select distinct supported custom-input dimensions")

    import torch
    import vbench

    run = args.run_dir.resolve()
    benchmark = json.loads((run / "plan.json").read_text())
    receipt = json.loads((run / "receipt.json").read_text())
    verify_manifest(benchmark, receipt)
    completed = {
        key: value
        for key, value in receipt["jobs"].items()
        if value["state"] == "completed"
    }
    if not completed:
        parser.error("no completed clips")
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    inputs = args.output.parent / "input"
    inputs.mkdir(mode=0o700)
    prompts = {}
    for job in benchmark["jobs"]:
        if job["id"] not in completed:
            continue
        source = run / f"{job['id']}.mp4"
        if sha256(source) != completed[job["id"]]["video"]["sha256"]:
            parser.error("saved clip checksum differs")
        shutil.copyfile(source, inputs / source.name)
        prompts[source.name] = job["request"]["prompt"]
    evaluator = vbench.VBench(
        torch.device(args.device),
        str(Path(vbench.__file__).with_name("VBench_full_info.json")),
        str(args.output.parent),
    )
    evaluator.evaluate(
        videos_path=str(inputs),
        name="quality",
        prompt_list=prompts,
        dimension_list=args.dimension,
        mode="custom_input",
        imaging_quality_preprocessing_mode="longer",
    )
    for name in prompts:
        if sha256(inputs / name) != completed[Path(name).stem]["video"]["sha256"]:
            parser.error("evaluator input changed")
    cache = Path.home() / ".cache"
    weights = {
        str(path.relative_to(cache)): sha256(path)
        for path in sorted(cache.rglob("*"))
        if path.is_file() and path.suffix in {".pt", ".pth", ".ckpt", ".safetensors"}
    }
    cached_sources = {
        str(path.relative_to(cache)): sha256(path)
        for path in sorted(cache.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".yaml", ".yml"}
    }
    value = {
        "schema_version": 1,
        "plan_id": benchmark["id"],
        "evaluator": {
            "name": "VBench",
            "revision": revision,
            "device": args.device,
            "cuda": torch.version.cuda,
            "mode": "custom_input",
            "imaging_quality_preprocessing_mode": "longer",
            "packages": package_versions(),
            "weights_sha256": weights,
            "cached_sources_sha256": cached_sources,
            "inputs_sha256": {
                key: value["video"]["sha256"] for key, value in completed.items()
            },
        },
        "results": json.loads(
            (args.output.parent / "quality_eval_results.json").read_text()
        ),
    }
    args.output.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    args.output.chmod(0o600)
    print(f"Evaluation saved: {args.output}")


if __name__ == "__main__":
    main()
