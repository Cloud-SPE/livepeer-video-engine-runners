#!/usr/bin/env python3
"""Switch an idle combined managed deployment through all three default models.

Use the local demo node or supply --discovery for your orchestrator. Stops on the
first failed request; generations are never automatically resubmitted.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from video_runners.tools.operator_io import read_env
from video_runners.tools.evidence import HostLease, RunReceipt, model_inputs

ROOT = Path(__file__).resolve().parents[3]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--discovery", default="")
    parser.add_argument("--signer", default="", help="Remote payment signer URL")
    parser.add_argument("--admin-url", default="")
    parser.add_argument(
        "--catalog-defaults",
        action="store_true",
        help="Use each model's default workload",
    )
    parser.add_argument(
        "--mode", choices=("single-shot", "persistent", "both"), default="both"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts/gpu-validation"
    )
    args = parser.parse_args()
    with (
        HostLease() as lease,
        RunReceipt(ROOT, args.output_dir, "gpu-switching") as receipt,
    ):
        args.output_dir = receipt.directory
        validate(args, parser, receipt, lease)


def validate(args, parser, receipt, lease):
    values = read_env(args.env_file)
    token = os.environ.get("RUNNER_ADMIN_TOKEN") or values.get("RUNNER_ADMIN_TOKEN")
    if not token:
        parser.error("set RUNNER_ADMIN_TOKEN or select the private deployment env file")
    admin = (
        args.admin_url or f"http://127.0.0.1:{values.get('RUNNER_ADMIN_PORT', '8990')}"
    )
    discovery = (
        args.discovery
        or f"http://127.0.0.1:{values.get('ORCHESTRATOR_PORT', '8935')}/discovery"
    )
    opener = urllib.request.build_opener(NoRedirect)

    def call(path, body=None):
        request = urllib.request.Request(
            admin.rstrip("/") + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with opener.open(request, timeout=7200) as response:
            return json.load(response)

    status = call("/admin/status")
    if (
        status["switching"]
        or status["gpu_busy"]
        or status["sessions"]
        or status["recovery_required"]
    ):
        parser.error("deployment must be healthy and idle, with no reserved sessions")
    defaults = json.loads((ROOT / "configs/model-assets.json").read_text())["defaults"]
    selected = [
        (engine, f"{engine}-{defaults[engine]}")
        for engine in ("sglang", "lightx2v", "vllm-omni")
    ]
    if not {model for _, model in selected}.issubset(status["catalog"]):
        parser.error(
            "start the combined managed catalog with ENGINE=all docker compose -f compose.dev.yml"
        )
    receipt.data["inputs"] = {
        "models": [model_inputs(ROOT, engine, model) for engine, model in selected],
        "mode": args.mode,
        "catalog_defaults": args.catalog_defaults,
        "paid_signer_requested": bool(args.signer),
    }
    receipt.save()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for engine, model in selected:
        print(f"Switching to {model}", flush=True)
        started = time.monotonic()
        call("/admin/model", {"model": model})
        switched = time.monotonic() - started
        # A remote signer's discovery snapshot can lag registration. Retry only
        # discovery, before submitting any generation or paid reservation.
        wanted = {
            f"video:{kind}/{model}"
            for mode, kind in (
                ("single-shot", "generations"),
                ("persistent", "sessions"),
            )
            if args.mode in ("both", mode)
        }
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                with opener.open(discovery, timeout=10) as response:
                    entries = json.load(response)
                apps = {
                    runner.get("app")
                    for entry in entries
                    for runner in entry.get("runners", [])
                }
                if wanted <= apps:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError(f"{model} did not appear in discovery within 90 seconds")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "src/video_runners/tools/validate_gpu.py"),
                "--engine",
                engine,
                "--model",
                model,
                "--discovery",
                discovery,
                "--mode",
                args.mode,
                "--signer",
                args.signer,
                "--output-dir",
                str(args.output_dir),
            ]
            + (["--catalog-defaults"] if args.catalog_defaults else []),
            check=True,
            pass_fds=(lease.fd,),
            env=lease.child_env(receipt.id),
        )
        records.append({"model": model, "switch_seconds": switched})
        receipt.result(records[-1])
        (args.output_dir / "switches.json").write_text(
            json.dumps(records, indent=2) + "\n"
        )
    if status["model"]:
        print(f"Restoring {status['model']}", flush=True)
        call("/admin/model", {"model": status["model"]})
    print("All three engines passed; initial model restored.", flush=True)


if __name__ == "__main__":
    main()
