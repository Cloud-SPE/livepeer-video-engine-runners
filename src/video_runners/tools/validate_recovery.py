#!/usr/bin/env python3
"""Inject owned-container faults into an idle offchain managed deployment.

Run on the Docker host. Checks durable controller ownership and trusted policy
before touching an engine; never restarts Docker or unrelated services. Each
case must recover and generate a fresh video before proceeding to the next.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
from string import Template
import subprocess
import sys
import time

import aiohttp
from livepeer_gateway.errors import LivepeerGatewayError, LivepeerHTTPError
from livepeer_gateway.http import post_json
from livepeer_gateway.live_runner import call_runner
from livepeer_gateway.selection import reserve_session, runner_selector

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from video_runners.controller.policy import Policy
from video_runners.tools.operator_io import command_output, read_env
from video_runners.tools.evidence import HostLease, RunReceipt, model_inputs

ROOT = Path(__file__).resolve().parents[3]
CASES = (
    "disconnect",
    "session-stop",
    "idle-engine-kill",
    "engine-kill",
    "runner-kill",
    "controller-restart",
)


def docker(*args):
    return command_output("docker", *args)


class Check:
    def __init__(self, args, receipt, lease):
        self.args, self.receipt, self.lease = args, receipt, lease
        self.values = read_env(args.env_file, ROOT / ".engine-images.env")
        self.project = self.values["COMPOSE_PROJECT_NAME"]
        self.values.setdefault("ENGINE_NAMESPACE", self.project)
        self.values.setdefault("ENGINE_NETWORK", self.project + "-engine")
        self.policy = Policy(
            json.loads(
                Template((ROOT / "configs/controller/all.json").read_text()).substitute(
                    self.values
                )
            )
        )
        volume = json.loads(
            docker("volume", "inspect", self.values["CONTROLLER_STATE_VOLUME"])
        )[0]
        self.state_path = Path(volume["Mountpoint"]) / "state.json"
        self.admin = "http://127.0.0.1:" + self.values.get("RUNNER_ADMIN_PORT", "8990")
        self.discovery = (
            args.discovery
            or "http://127.0.0.1:"
            + self.values.get("ORCHESTRATOR_PORT", "8935")
            + "/discovery"
        )
        self.model = ""
        self.http = None
        self.observations = []
        receipt = args.output_dir / f"{args.engine}-recovery.json"
        if receipt.exists():
            self.observations = json.loads(receipt.read_text())

    async def api(self, path, body=None):
        async with self.http.request(
            "GET" if body is None else "POST",
            self.admin + path,
            json=body,
            headers={"Authorization": "Bearer " + self.values["RUNNER_ADMIN_TOKEN"]},
            timeout=aiohttp.ClientTimeout(total=7200),
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"admin HTTP {response.status}: {(await response.text())[:300]}"
                )
            return await response.json()

    def engine(self):
        state = json.loads(self.state_path.read_text())
        if state["namespace"] != self.policy.namespace or len(state["containers"]) != 1:
            raise RuntimeError("expected exactly one recorded engine in this namespace")
        identifier, model = next(iter(state["containers"].items()))
        actual = json.loads(docker("inspect", identifier))[0]
        self.policy.verify(model, actual)
        if model != self.model or not actual["State"]["Running"]:
            raise RuntimeError("recorded engine is not the selected running model")
        return identifier

    def service(self, name):
        compose = [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(self.args.env_file.resolve()),
        ]
        images = ROOT / ".engine-images.env"
        if images.exists():
            compose += ["--env-file", str(images)]
        existing = self.values.get("USE_EXISTING_ORCHESTRATOR") == "1"
        compose += [
            "-f",
            str(ROOT / ("compose.prod.yml" if existing else "compose.dev.yml")),
        ]
        if existing and self.values.get("EXISTING_ORCHESTRATOR_NETWORK"):
            compose += ["-f", str(ROOT / "deploy/compose/ingress.yml")]
        result = subprocess.check_output(
            [*compose, "ps", "-q", name],
            cwd=ROOT,
            env={**os.environ, **self.values},
            text=True,
        ).strip()
        actual = json.loads(docker("inspect", result))[0]
        labels = actual["Config"]["Labels"]
        if (
            labels.get("com.docker.compose.project") != self.project
            or labels.get("com.docker.compose.service") != name
        ):
            raise RuntimeError("Compose service ownership differs")
        return result

    async def ready(self, changed_from=None):
        deadline = time.monotonic() + self.args.timeout
        last = None
        while time.monotonic() < deadline:
            # Read-only observation of all running engines in our own namespace.
            ids = docker(
                "ps",
                "-q",
                "--filter",
                "label=io.livepeer.video.owner=" + self.policy.namespace,
            ).split()
            if len(ids) > 1:
                raise RuntimeError(
                    "more than one engine is running in the test namespace"
                )
            try:
                last = await self.api("/admin/status")
                if (
                    last["model"] == self.model
                    and not last["switching"]
                    and not last["gpu_busy"]
                    and not last["recovery_required"]
                    and not last["sessions"]
                    and len(last["registrations"]) == 2
                ):
                    identifier = self.engine()
                    if changed_from and identifier == changed_from:
                        await asyncio.sleep(1)
                        continue
                    cursor = await runner_selector(
                        discovery_url=self.discovery,
                        app=f"video:generations/{self.model}",
                    )
                    if cursor.candidates:
                        return identifier
            except (
                aiohttp.ClientError,
                LivepeerGatewayError,
                subprocess.CalledProcessError,
                RuntimeError,
                ValueError,
                KeyError,
                FileNotFoundError,
            ):
                pass
            await asyncio.sleep(1)
        raise RuntimeError(
            f"recovery did not finish in {self.args.timeout}s; last status={last}"
        )

    async def wait_busy(self):
        async with asyncio.timeout(10):
            while not (await self.api("/admin/status"))["gpu_busy"]:
                await asyncio.sleep(0.05)

    async def fault(self, case):
        before = self.engine()
        started = time.monotonic()
        busy_rejection = None
        if case == "disconnect":
            cursor = await runner_selector(
                discovery_url=self.discovery, app=f"video:generations/{self.model}"
            )
            async with await call_runner(
                runner=cursor.candidates[0],
                runner_url=cursor.candidates[0].url.rstrip("/") + "/generate",
                payload={
                    "prompt": "A red fox walking through a snowy forest",
                    "seed": 99,
                },
                stream=True,
            ) as stream:
                async for line in stream.aiter_lines():
                    if line.startswith("event: status"):
                        await self.wait_busy()
                        break
                else:
                    raise RuntimeError(
                        "generation ended before the disconnect injection"
                    )
        elif case in {"session-stop", "engine-kill"}:
            candidate = (
                await runner_selector(
                    discovery_url=self.discovery, app=f"video:generations/{self.model}"
                )
            ).candidates[0]
            session = await reserve_session(
                discovery_url=self.discovery, app=f"video:sessions/{self.model}"
            )
            await session.__aenter__()
            try:
                await post_json(session.app_url.rstrip("/") + "/session/start", {})
                await post_json(
                    session.app_url.rstrip("/") + "/session/jobs",
                    {
                        "prompt": "A red fox walking through a snowy forest",
                        "seed": 100,
                    },
                )
                await self.wait_busy()
                await asyncio.sleep(0.5)
                if case == "session-stop":
                    try:
                        async with await call_runner(
                            runner=candidate,
                            runner_url=candidate.url.rstrip("/") + "/generate",
                            payload={
                                "prompt": "This concurrent test job must be rejected"
                            },
                            stream=True,
                        ):
                            raise RuntimeError(
                                "a concurrent generation was accepted while the GPU was busy"
                            )
                    except LivepeerHTTPError as error:
                        if error.status_code != 503:
                            raise
                        busy_rejection = error.status_code
                if case == "engine-kill":
                    # Recheck durable identity and policy immediately before
                    # killing an engine with a known in-flight test job.
                    assert self.engine() == before
                    docker("kill", before)
            finally:
                try:
                    await session.aclose()
                except LivepeerHTTPError as error:
                    # Recovery unregisters the old runner and releases its
                    # sessions; a stop of that already-released ID is 404.
                    if error.status_code != 404:
                        raise
        elif case == "idle-engine-kill":
            docker("kill", before)
        elif case == "runner-kill":
            identifier = self.service("runner")
            actual = json.loads(docker("inspect", identifier))[0]
            pid = actual["State"]["Pid"]
            if not actual["State"]["Running"] or pid <= 1:
                raise RuntimeError("verified runner has no running host process")
            # Docker's kill API marks an intentional operator stop and suppresses
            # restart policy. Crash the verified process instead. A pidfd pins
            # process identity so PID reuse cannot target an unrelated process.
            descriptor = os.pidfd_open(pid)
            try:
                current = json.loads(docker("inspect", identifier))[0]
                if current["State"]["Pid"] != pid or not current["State"]["Running"]:
                    raise RuntimeError("runner changed before crash injection")
                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            finally:
                os.close(descriptor)
        else:
            docker("restart", "-t", "30", self.service("controller"))
        injected = time.monotonic()
        after = await self.ready(changed_from=before if case != "disconnect" else None)
        record = {
            "case": case,
            "model": self.model,
            "engine_before": before,
            "engine_after": after,
            "engine_replaced": before != after,
            "injection_seconds": injected - started,
            "recovery_seconds": time.monotonic() - injected,
            "concurrent_generation_rejected_http": busy_rejection,
        }
        self.observations.append(record)
        self.save()
        print(json.dumps(record), flush=True)
        if not self.args.skip_generation:
            directory = self.args.output_dir / self.args.engine / case
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(ROOT / "src/video_runners/tools/validate_gpu.py"),
                "--engine",
                self.args.engine,
                "--model",
                self.model,
                "--discovery",
                self.discovery,
                "--mode",
                "single-shot",
                "--gpu",
                self.values["ENGINE_GPU_UUID"],
                "--engine-container",
                after,
                "--output-dir",
                str(directory),
                pass_fds=(self.lease.fd,),
                env=self.lease.child_env(self.receipt.id),
            )
            result = await process.wait()
            if result:
                raise RuntimeError(
                    "fresh generation after recovery failed; no retry was submitted"
                )
            record["fresh_generation_verified"] = True
            self.save()

    def save(self):
        self.receipt.data["results"] = self.observations
        self.receipt.save()
        self.args.output_dir.mkdir(parents=True, exist_ok=True)
        (self.args.output_dir / f"{self.args.engine}-recovery.json").write_text(
            json.dumps(self.observations, indent=2) + "\n"
        )

    async def run(self):
        defaults = json.loads((ROOT / "configs/model-assets.json").read_text())[
            "defaults"
        ]
        self.model = self.args.engine + "-" + defaults[self.args.engine]
        self.receipt.data["inputs"] = {
            **model_inputs(ROOT, self.args.engine, self.model),
            "cases": list(self.args.cases),
            "scope": (
                "readiness_only"
                if self.args.skip_generation
                else "recovery_and_generation"
            ),
        }
        self.receipt.save()
        async with aiohttp.ClientSession() as self.http:
            async with self.http.get(
                self.discovery, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response.raise_for_status()
                entries = await response.json()
            if any(
                runner.get("price_info")
                for entry in entries
                for runner in entry.get("runners", [])
            ):
                raise RuntimeError(
                    "fault validation requires the free offchain test node; "
                    "paid fault injection is not supported"
                )
            initial = await self.api("/admin/status")
            if (
                initial["gpu_busy"]
                or initial["sessions"]
                or initial["switching"]
                or initial["recovery_required"]
            ):
                raise RuntimeError(
                    "fault injection requires an idle healthy deployment"
                )
            await self.api("/admin/model", {"model": self.model})
            await self.ready()
            for case in self.args.cases:
                print(f"Injecting {case} for {self.model}", flush=True)
                await self.fault(case)
        print(
            f"All {len(self.observations)} recovery cases passed for {self.model}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine", choices=("sglang", "lightx2v", "vllm-omni"), required=True
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--discovery", default="")
    parser.add_argument("--cases", choices=CASES, nargs="+", default=CASES)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts/gpu-validation/recovery"
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="Readiness-only diagnostic; does not establish generation recovery",
    )
    args = parser.parse_args()
    with (
        HostLease() as lease,
        RunReceipt(ROOT, args.output_dir, "gpu-recovery") as receipt,
    ):
        if args.skip_generation:
            receipt.data["outcome"] = "readiness_only"
        args.output_dir = receipt.directory
        asyncio.run(Check(args, receipt, lease).run())


if __name__ == "__main__":
    main()
