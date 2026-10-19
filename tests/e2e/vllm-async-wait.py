#!/usr/bin/env python3
"""Check a prepared vLLM image's warmup wait without a GPU or engine imports."""

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess


def check_wait():
    spec = importlib.util.find_spec("vllm_omni")
    source = Path(spec.origin).parent / "diffusion/diffusion_engine.py"
    text = source.read_text()
    tree = ast.parse(text)
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id.startswith("_ASYNC_OUTPUT_TIMEOUT")
            for target in node.targets
        ):
            selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "_async_output_timeout":
            selected.append(node)
    engine = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DiffusionEngine"
    )
    warmup = next(
        node
        for node in engine.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "add_req_and_wait_for_response"
    )
    waits = [
        node
        for node in ast.walk(warmup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "fut"
        and node.func.attr == "result"
        and any(keyword.arg == "timeout" for keyword in node.keywords)
    ]
    assert len(waits) == 1, "Review the changed upstream warmup wait contract"

    class SlowOutput:
        """Model Future.result's deadline contract without sleeping or inference."""

        timeout = None

        def result(self, *, timeout):
            self.timeout = timeout
            if timeout < 30 + 1:
                raise TimeoutError("A healthy 31-second step exceeded the wait")
            return "output-ready"

    output = SlowOutput()
    namespace = {"os": os, "fut": output}
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    try:
        result = eval(compile(ast.Expression(waits[0]), str(source), "eval"), namespace)
        ready = result == "output-ready"
    except TimeoutError:
        ready = False
    print(
        json.dumps(
            dict(
                ready=ready,
                effective_timeout_seconds=output.timeout,
                modeled_output_ready_seconds=31,
                source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                inference_performed=False,
            )
        ),
        flush=True,
    )
    return 0 if ready else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        raise SystemExit(check_wait())
    image = (
        args.image
        or json.loads(
            (
                Path(__file__).resolve().parents[2] / "configs/engine-images.json"
            ).read_text()
        )["vllm-omni"]
    )
    probe = str(Path(__file__).resolve())
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--name",
            "vr-vllm-wait-" + secrets.token_hex(5),
            "--runtime=runc",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--entrypoint=python",
            "-e",
            "VLLM_OMNI_ASYNC_OUTPUT_TIMEOUT=600",
            "--mount",
            f"type=bind,source={probe},target=/probe.py,readonly",
            image,
            "/probe.py",
            "--inside",
        ],
        check=False,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
