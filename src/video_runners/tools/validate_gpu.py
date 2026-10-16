#!/usr/bin/env python3
"""Generate real clips through Livepeer and verify every frame decodes.

Run inside the project's locked Python environment on the GPU deployment host.
The runner and engine must already be healthy; this tool never resubmits a job.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from video_runners.tools.evidence import (
    HostLease,
    RunReceipt,
    atomic_json,
    model_inputs,
)

ROOT = Path(__file__).resolve().parents[3]
PROMPT = "A small red fox walks slowly across a snowy forest clearing. Soft golden sunlight, realistic fur, gentle camera movement, cinematic natural colors."
DEFAULT_MODELS = json.loads((ROOT / "configs/model-assets.json").read_text())[
    "defaults"
]


class Telemetry:
    """Host-side sampling; no Docker or GPU access is needed by the runner."""

    def __init__(self, gpu: str, container: str, output: Path):
        self.gpu, self.container, self.output = gpu, container, output
        self.samples = []
        self.stopped = threading.Event()
        self.thread = None
        self.cgroup = None

    def __enter__(self):
        if self.container:
            pid = subprocess.check_output(
                ["docker", "inspect", "--format", "{{.State.Pid}}", self.container],
                text=True,
            ).strip()
            for line in Path(f"/proc/{int(pid)}/cgroup").read_text().splitlines():
                if line.startswith("0::"):
                    self.cgroup = Path("/sys/fs/cgroup") / line[3:].lstrip("/")
        if self.gpu or self.cgroup:
            self.thread = threading.Thread(target=self.monitor, daemon=True)
            self.thread.start()
        return self

    def monitor(self):
        while not self.stopped.is_set():
            sample = {"monotonic": time.monotonic()}
            try:
                if self.gpu:
                    row = (
                        subprocess.check_output(
                            [
                                "nvidia-smi",
                                "-i",
                                self.gpu,
                                "--query-gpu=memory.used,utilization.gpu",
                                "--format=csv,noheader,nounits",
                            ],
                            text=True,
                            timeout=5,
                        )
                        .strip()
                        .split(",")
                    )
                    sample.update(gpu_mib=float(row[0]), gpu_utilization=float(row[1]))
                if self.cgroup:
                    sample["engine_memory_bytes"] = int(
                        (self.cgroup / "memory.current").read_text()
                    )
                    sample["engine_lifetime_peak_bytes"] = int(
                        (self.cgroup / "memory.peak").read_text()
                    )
                    sample["engine_oom_kills"] = int(
                        dict(
                            line.split()
                            for line in (self.cgroup / "memory.events")
                            .read_text()
                            .splitlines()
                        )["oom_kill"]
                    )
                    memory_stat = dict(
                        line.split()
                        for line in (self.cgroup / "memory.stat")
                        .read_text()
                        .splitlines()
                    )
                    sample["engine_anon_bytes"] = int(memory_stat["anon"])
                    sample["engine_file_cache_bytes"] = int(memory_stat["file"])
                memory = dict(
                    line.split(":", 1)
                    for line in Path("/proc/meminfo").read_text().splitlines()
                )
                sample["host_available_kib"] = int(memory["MemAvailable"].split()[0])
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                sample["error"] = str(exc)
            self.samples.append(sample)
            self.stopped.wait(0.5)

    def __exit__(self, *exc):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=10)
        self.output.write_text(json.dumps(self.samples, indent=2) + "\n")

    def summary(self):
        def maximum(key):
            return max(
                (sample[key] for sample in self.samples if key in sample), default=None
            )

        return {
            "sample_interval_seconds": 0.5,
            "samples": len(self.samples),
            "gpu_sampled_peak_mib": maximum("gpu_mib"),
            "engine_sampled_peak_bytes": maximum("engine_memory_bytes"),
            "engine_lifetime_peak_bytes": maximum("engine_lifetime_peak_bytes"),
            "engine_anon_sampled_peak_bytes": maximum("engine_anon_bytes"),
            "engine_file_cache_sampled_peak_bytes": maximum("engine_file_cache_bytes"),
            "engine_oom_kills": maximum("engine_oom_kills"),
            "sampling_errors": [s["error"] for s in self.samples if "error" in s],
        }


def verify_video(path: Path) -> dict:
    import av

    hashes, preview = set(), None
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate)
        width, height = stream.width, stream.height
        frames = 0
        for frame in container.decode(stream):
            hashes.add(
                hashlib.sha256(frame.to_ndarray(format="rgb24").tobytes()).hexdigest()
            )
            frames += 1
            if frames == 25 or preview is None:
                preview = frame
    if frames < 8 or len(hashes) < 2 or fps <= 0:
        raise ValueError("output must contain a decodable video with changing frames")
    preview_path = path.with_suffix(".png")
    with av.open(str(preview_path), mode="w", format="image2") as output:
        picture = output.add_stream("png", rate=1)
        picture.width, picture.height = width, height
        picture.pix_fmt = "rgb24"
        for packet in picture.encode(preview.reformat(format="rgb24")):
            output.mux(packet)
        for packet in picture.encode():
            output.mux(packet)
    return {
        "file": str(path),
        "preview": str(preview_path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "width": width,
        "height": height,
        "frames": frames,
        "fps": fps,
        "duration_seconds": frames / fps,
        "unique_frames": len(hashes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=DEFAULT_MODELS, required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--discovery", default="http://127.0.0.1:8935/discovery")
    parser.add_argument("--signer", default="", help="Remote payment signer URL")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts/gpu-validation"
    )
    parser.add_argument(
        "--mode", choices=("single-shot", "persistent", "both"), default="both"
    )
    parser.add_argument(
        "--catalog-defaults",
        action="store_true",
        help="Use the model's configured resolution and frames instead of the small smoke test",
    )
    parser.add_argument(
        "--clips", type=int, default=1, help="Number of clips in the persistent session"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat each delivery mode; each repetition is a new explicit job",
    )
    parser.add_argument(
        "--gpu", default="", help="GPU UUID for host-side NVIDIA memory sampling"
    )
    parser.add_argument(
        "--engine-container",
        default="",
        help="Current engine container ID for cgroup v2 memory sampling",
    )
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--num-frames", type=int)
    args = parser.parse_args()
    with (
        HostLease() as lease,
        RunReceipt(ROOT, args.output_dir, "gpu-generation") as receipt,
    ):
        args.output_dir = receipt.directory
        validate(args, parser, receipt, lease)


def validate(args, parser, receipt, lease):
    if args.clips < 1 or args.repeat < 1:
        parser.error("--clips and --repeat must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model = args.model or DEFAULT_MODELS[args.engine]
    catalog_name = "all" if model.startswith(args.engine + "-") else args.engine
    catalog = json.loads((ROOT / f"models/{catalog_name}.json").read_text())
    entries = {entry["id"]: entry for entry in catalog["models"]}
    if model not in entries:
        parser.error("model is not in the selected public catalog")
    expected = dict(entries[model].get("defaults", {}))
    if not args.catalog_defaults:
        expected.update(width=512, height=288, num_frames=49)
    overrides = {
        key: getattr(args, key)
        for key in ("width", "height", "num_frames")
        if getattr(args, key) is not None
    }
    expected.update(overrides)
    receipt.data["inputs"] = {
        **model_inputs(ROOT, args.engine, model, args.engine_container),
        "requested": expected,
        "seed": 42,
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "mode": args.mode,
        "repeat": args.repeat,
        "clips": args.clips,
        "paid_signer_requested": bool(args.signer),
        "gpu": None,
    }
    if args.gpu:
        row = (
            subprocess.check_output(
                [
                    "nvidia-smi",
                    "-i",
                    args.gpu,
                    "--query-gpu=uuid,name,driver_version",
                    "--format=csv,noheader",
                ],
                text=True,
            )
            .strip()
            .split(",")
        )
        receipt.data["inputs"]["gpu"] = dict(
            zip(("uuid", "name", "driver_version"), (value.strip() for value in row))
        )
    receipt.save()
    modes = ("single-shot", "persistent") if args.mode == "both" else (args.mode,)
    for mode, repetition in ((m, n) for m in modes for n in range(args.repeat)):
        suffix = f"-r{repetition}" if args.repeat > 1 else ""
        prefix = args.output_dir / f"{args.engine}-{mode}{suffix}"
        command = [
            sys.executable,
            "-m",
            "video_runners.client",
            "--discovery",
            args.discovery,
            "--model",
            model,
            "--mode",
            mode,
            "--clips",
            str(args.clips),
            "--prompt",
            PROMPT,
            "--seed",
            "42",
            "--output",
            str(prefix),
        ]
        if not args.catalog_defaults:
            command += ["--width", "512", "--height", "288", "--num-frames", "49"]
        if args.signer:
            command += ["--signer", args.signer]
        for key, value in overrides.items():
            command += ["--" + key.replace("_", "-"), str(value)]
        started = time.monotonic()
        with (
            Telemetry(
                args.gpu, args.engine_container, prefix.with_suffix(".metrics.json")
            ) as telemetry,
            prefix.with_suffix(".log").open("w") as log,
        ):
            subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                pass_fds=(lease.fd,),
                env=lease.child_env(receipt.id),
            )
        elapsed = time.monotonic() - started
        for index in range(args.clips if mode == "persistent" else 1):
            path = Path(
                str(prefix) + (f"-{index:03}.mp4" if mode == "persistent" else ".mp4")
            )
            verified = verify_video(path)
            for field, requested in (
                ("width", "width"),
                ("height", "height"),
                ("frames", "num_frames"),
            ):
                if requested in expected and verified[field] != expected[requested]:
                    raise ValueError(
                        f"video {field}={verified[field]} does not match requested {expected[requested]}"
                    )
            result = {
                "engine": args.engine,
                "model": model,
                "mode": mode,
                "run_id": receipt.id,
                "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
                "seed": 42 + index,
                "request_seconds": elapsed,
                "request_clips": args.clips if mode == "persistent" else 1,
                "requested": expected,
                "telemetry": telemetry.summary(),
                **verified,
            }
            atomic_json(path.with_suffix(".json"), result)
            receipt.result(result)
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
