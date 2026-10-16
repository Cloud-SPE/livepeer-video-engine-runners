"""Quality planning and resumability use no GPU, Docker or funded signer."""

import json
import asyncio
import hashlib
import subprocess
import sys
from aiohttp import web

import pytest

from video_runners.tools.quality import generate, plan, report, score, summarize


def suite_fixture(tmp_path):
    (tmp_path / "catalog.json").write_text(
        json.dumps(
            {
                "default": "sample",
                "models": [
                    {
                        "id": "sample",
                        "engine": "openai-videos",
                        "command": ["vllm", "serve", "example/model"],
                        "port": 9100,
                        "defaults": {"width": 832, "height": 480, "steps": 30},
                    }
                ],
            }
        )
    )
    (tmp_path / "prompts.jsonl").write_text(
        json.dumps(
            {
                "id": "fox",
                "prompt": "A red fox walks in snow.",
                "criteria": ["continuous walking"],
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "wave",
                "prompt": "A wave breaks on a beach.",
                "criteria": ["continuous water motion"],
            }
        )
        + "\n"
    )
    suite = tmp_path / "suites.json"
    suite.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalog": "catalog.json",
                "prompts": "prompts.jsonl",
                "experiments": [
                    {"id": "current", "model": "sample", "parameters": {}},
                    {"id": "quality", "model": "sample", "parameters": {"steps": 50}},
                ],
                "suites": {
                    "screen": {
                        "prompts": ["fox", "wave"],
                        "seeds": [42, 123],
                        "experiments": ["current", "quality"],
                    }
                },
            }
        )
    )
    return suite


def test_plan_expands_prompts_seeds_and_experiments_reproducibly(tmp_path):
    suite = suite_fixture(tmp_path)
    first = plan(suite, "screen")
    assert len(first["jobs"]) == 2 * 2 * 2
    assert len({job["id"] for job in first["jobs"]}) == 8
    assert {job["request"]["steps"] for job in first["jobs"]} == {30, 50}
    assert first == plan(suite, "screen")
    subset = plan(suite, "screen", experiments=("quality",))
    assert len(subset["jobs"]) == 2 * 2
    assert {job["id"] for job in subset["jobs"]} <= {job["id"] for job in first["jobs"]}


@pytest.mark.parametrize(
    "change", ["unknown", "zero", "duplicate", "seed", "light-steps"]
)
def test_plan_rejects_ambiguous_or_unsupported_controls(tmp_path, change):
    suite = suite_fixture(tmp_path)
    data = json.loads(suite.read_text())
    if change == "unknown":
        data["experiments"][0]["parameters"] = {"mystery_knob": 5}
    elif change == "zero":
        data["experiments"][0]["parameters"] = {"steps": 0}
    elif change == "duplicate":
        data["experiments"].append(data["experiments"][0])
    elif change == "seed":
        data["suites"]["screen"]["seeds"] = [True]
    else:
        catalog = tmp_path / "catalog.json"
        models = json.loads(catalog.read_text())
        models["models"][0]["engine"] = "lightx2v"
        catalog.write_text(json.dumps(models))
    suite.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        plan(suite, "screen")


def test_uncertain_submission_is_never_retried_on_resume(tmp_path):
    benchmark = plan(suite_fixture(tmp_path), "screen")
    calls = []

    async def disconnected(job, path):
        calls.append(job["id"])
        raise ConnectionError("outcome cannot be established")

    directory = tmp_path / "run"
    with pytest.raises(ConnectionError):
        asyncio.run(generate(benchmark, directory, disconnected))
    with pytest.raises(RuntimeError, match="uncertain"):
        asyncio.run(generate(benchmark, directory, disconnected))
    assert calls == [benchmark["jobs"][0]["id"]]


def test_resume_checks_saved_video_before_submitting_another_job(tmp_path):
    benchmark = plan(suite_fixture(tmp_path), "screen")
    calls = []

    async def render(job, path):
        calls.append(job["id"])
        path.write_bytes(b"completed video")

    def inspect(path):
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    directory = tmp_path / "run"
    asyncio.run(generate(benchmark, directory, render, inspect=inspect, max_jobs=1))
    assert calls == [benchmark["jobs"][0]["id"]]
    asyncio.run(generate(benchmark, directory, render, inspect=inspect, max_jobs=1))
    assert calls == [job["id"] for job in benchmark["jobs"][:2]]
    (directory / f"{calls[0]}.mp4").write_bytes(b"corrupted")
    with pytest.raises(RuntimeError, match="checksum"):
        asyncio.run(generate(benchmark, directory, render, inspect=inspect, max_jobs=1))
    assert len(calls) == 2


def test_concurrent_invocation_cannot_submit_the_same_run(tmp_path):
    benchmark = plan(suite_fixture(tmp_path), "screen")

    async def scenario():
        started = asyncio.Event()

        async def render(job, path):
            started.set()
            await asyncio.Event().wait()

        first = asyncio.create_task(generate(benchmark, tmp_path / "run", render))
        await started.wait()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                await generate(benchmark, tmp_path / "run", render)
        finally:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first

    asyncio.run(scenario())


def test_report_blinds_model_identity_and_escapes_prompt_content(tmp_path):
    suite = suite_fixture(tmp_path)
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text(
        json.dumps(
            {
                "id": "fox",
                "prompt": "A fox <img src=x onerror=alert(1)>",
                "criteria": ["stable face"],
            }
        )
        + "\n"
    )
    data = json.loads(suite.read_text())
    data["suites"]["screen"].update(prompts=["fox"], seeds=[42])
    suite.write_text(json.dumps(data))
    benchmark = plan(suite, "screen")

    async def render(job, path):
        path.write_bytes(job["experiment"].encode())

    directory = tmp_path / "run"
    asyncio.run(
        generate(
            benchmark,
            directory,
            render,
            inspect=lambda p: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
        )
    )
    output = tmp_path / "review"
    report([directory], output)
    assert (output / "index.html").exists()
    html = (output / "index.html").read_text()
    assert "example/model" not in html
    assert "<img src=x" not in html and "&lt;img" in html
    assert "Export ratings" in html and "Play together" in html
    key = json.loads(output.with_name(output.name + ".key.json").read_text())
    assert not (output / "key.json").exists()
    assert len(key["pairs"]) == 1
    assert {side["experiment"] for side in key["pairs"][0]["sides"]} == {
        "current",
        "quality",
    }
    assert len(list((output / "videos").glob("*.mp4"))) == 2


def test_configured_input_changes_invalidate_the_plan_and_job_identity(tmp_path):
    suite = suite_fixture(tmp_path)
    data = json.loads(suite.read_text())
    data["provenance"] = ["asset-pin.json"]
    data["experiments"][0]["parameters"] = {"guidance_scale": 5, "flow_shift": 8}
    suite.write_text(json.dumps(data))
    pin = tmp_path / "asset-pin.json"
    pin.write_text(json.dumps({"revision": "a" * 40}))
    first = plan(suite, "screen")
    pin.write_text(json.dumps({"revision": "b" * 40}))
    second = plan(suite, "screen")
    assert first["id"] != second["id"]
    assert {j["id"] for j in first["jobs"]}.isdisjoint(j["id"] for j in second["jobs"])
    assert first["jobs"][0]["request"]["guidance_scale"] == 5.0
    assert (
        first["inputs"]["configured_files"]["asset-pin.json"]["content"]["revision"]
        == "a" * 40
    )


def test_perceptual_scores_are_bound_to_verified_videos_and_evaluator_revision(
    tmp_path,
):
    benchmark = plan(suite_fixture(tmp_path), "screen")

    async def render(job, path):
        path.write_bytes(b"completed video")

    directory = tmp_path / "run"
    asyncio.run(
        generate(
            benchmark,
            directory,
            render,
            inspect=lambda p: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
            max_jobs=1,
        )
    )
    job_id = benchmark["jobs"][0]["id"]
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "subject_consistency": [
                    0.9,
                    [{"video_path": f"/evaluation/{job_id}.mp4", "video_results": 0.9}],
                ]
            }
        )
    )
    score(directory, results, "c" * 40)
    stored = json.loads((directory / "scores.json").read_text())
    assert stored["evaluator"]["revision"] == "c" * 40
    assert stored["scores_by_job"][job_id]["metrics"] == {"subject_consistency": 0.9}
    assert "motion_smoothness" in stored["missing_dimensions"]
    results.write_text(
        json.dumps(
            {
                "subject_consistency": [
                    0.9,
                    [{"video_path": "/evaluation/foreign.mp4", "video_results": 0.9}],
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="video"):
        score(directory, results, "c" * 40)


def test_cli_plan_writes_private_manifest_without_running_services(tmp_path):
    suite = suite_fixture(tmp_path)
    output = tmp_path / "plan.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_runners.tools.quality",
            "plan",
            "--suite-file",
            str(suite),
            "--suite",
            "screen",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.exists()
    assert len(json.loads(output.read_text())["jobs"]) == 8
    assert output.stat().st_mode & 0o777 == 0o600


def test_cli_checks_discovery_before_recording_a_submission(tmp_path):
    benchmark = plan(suite_fixture(tmp_path), "screen")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(benchmark))

    async def scenario():
        app = web.Application()

        async def empty(request):
            return web.json_response([])

        app.router.add_get("/discovery", empty)
        server = web.AppRunner(app)
        await server.setup()
        site = web.TCPSite(server, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "video_runners.tools.quality",
                "generate",
                "--plan",
                str(path),
                "--run-dir",
                str(tmp_path / "run"),
                "--discovery",
                f"http://127.0.0.1:{port}/discovery",
                "--signer",
                "",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), 10)
            assert process.returncode == 1
            assert not (tmp_path / "run/receipt.json").exists()
        finally:
            await server.cleanup()

    asyncio.run(scenario())


def test_changed_plan_identity_is_rejected_before_submission(tmp_path):
    benchmark = plan(suite_fixture(tmp_path), "screen")
    benchmark["jobs"][0]["request"]["steps"] = 99
    calls = []

    async def render(job, path):
        calls.append(job)
        path.write_bytes(b"video")

    with pytest.raises(RuntimeError, match="plan"):
        asyncio.run(
            generate(
                benchmark,
                tmp_path / "run",
                render,
                inspect=lambda p: {
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest()
                },
            )
        )
    assert calls == []


def test_engine_ignoring_requested_dimensions_is_not_a_verified_result(tmp_path):
    benchmark = plan(suite_fixture(tmp_path), "screen")

    async def render(job, path):
        path.write_bytes(b"valid but wrong-size video")

    def inspect(path):
        return {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": 416,
            "height": 240,
        }

    with pytest.raises(ValueError, match="width"):
        asyncio.run(
            generate(benchmark, tmp_path / "run", render, inspect=inspect, max_jobs=1)
        )


@pytest.mark.parametrize(
    ("engine", "default", "models"),
    [
        ("sglang", "fastwan2.1-t2v-1.3b", {"fastwan2.1-t2v-1.3b", "wan2.1-t2v-1.3b"}),
        ("lightx2v", "wan2.1-t2v-1.3b", {"wan2.1-t2v-1.3b", "minimax-h3-4step"}),
        ("vllm-omni", "wan2.2-ti2v-5b", {"wan2.2-ti2v-5b", "wan2.2-t2v-a14b"}),
    ],
)
def test_quality_work_preserves_existing_models_and_defaults(engine, default, models):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    catalog = json.loads((root / "models" / f"{engine}.json").read_text())
    assert catalog["default"] == default
    assert models <= {entry["id"] for entry in catalog["models"]}


def test_evaluator_attestation_cannot_name_different_video_bytes(tmp_path):
    benchmark = plan(suite_fixture(tmp_path), "screen")

    async def render(job, path):
        path.write_bytes(b"completed video")

    directory = tmp_path / "run"
    asyncio.run(
        generate(
            benchmark,
            directory,
            render,
            inspect=lambda p: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
            max_jobs=1,
        )
    )
    job_id = benchmark["jobs"][0]["id"]
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "plan_id": benchmark["id"],
                "evaluator": {
                    "revision": "c" * 40,
                    "inputs_sha256": {job_id: "0" * 64},
                },
                "results": {
                    "subject_consistency": [
                        0.9,
                        [{"video_path": f"{job_id}.mp4", "video_results": 0.9}],
                    ]
                },
            }
        )
    )
    with pytest.raises(ValueError, match="checksum"):
        score(directory, path, "c" * 40)


def test_review_summary_joins_blind_preferences_with_the_matching_report():
    key = {
        "schema_version": 1,
        "report_id": "report-1",
        "pairs": [
            {
                "id": "pair-1",
                "sides": [
                    {"experiment": "first", "job_id": "clip-1"},
                    {"experiment": "second", "job_id": "clip-2"},
                ],
            }
        ],
    }
    ratings = {
        "schema_version": 1,
        "report_id": "report-1",
        "ratings": [
            {"pair_id": "pair-1", "preference": "A", "usability": ["yes", "no"]}
        ],
    }
    result = summarize(key, ratings)
    assert result["experiments"].get("first", {}).get("wins") == 1
    assert result["experiments"]["second"]["losses"] == 1
    assert result["experiments"]["first"]["usable_fraction"] == 1
    assert result["experiments"]["second"]["usable_fraction"] == 0
    ratings["report_id"] = "foreign-report"
    with pytest.raises(ValueError, match="report"):
        summarize(key, ratings)


def test_evaluator_respects_the_existing_controller_gpu_lease(tmp_path):
    import fcntl
    from video_runners.tools.quality_vbench import reserve_gpu

    path = tmp_path / "GPU-example.lock"
    with path.open("a") as controller:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="GPU"):
            with reserve_gpu(tmp_path, "GPU-example"):
                pass
    with reserve_gpu(tmp_path, "GPU-example"):
        pass


@pytest.mark.parametrize("consumer", ["report", "score", "worker"])
def test_offline_consumers_reject_receipts_from_another_plan(tmp_path, consumer):
    benchmark = plan(suite_fixture(tmp_path), "screen")
    directory = tmp_path / "run"

    async def render(job, path):
        path.write_bytes(b"clip")

    asyncio.run(
        generate(
            benchmark,
            directory,
            render,
            max_jobs=1,
            inspect=lambda p: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
        )
    )
    receipt_file = directory / "receipt.json"
    receipt = json.loads(receipt_file.read_text())
    receipt["plan_id"] = "0" * 64
    receipt_file.write_text(json.dumps(receipt))
    results = tmp_path / "results.json"
    results.write_text("{}")
    with pytest.raises(RuntimeError, match="receipt"):
        if consumer == "report":
            report([directory], tmp_path / "review")
        elif consumer == "score":
            score(directory, results, "c" * 40)
        else:
            from video_runners.tools.quality_vbench import verify_manifest

            verify_manifest(benchmark, receipt)


def test_evaluator_records_resolved_package_versions_when_base_has_duplicates(
    monkeypatch,
):
    from types import SimpleNamespace
    from video_runners.tools import quality_vbench

    monkeypatch.setattr(
        quality_vbench.metadata,
        "distributions",
        lambda: [
            SimpleNamespace(metadata={"Name": "example"}, version="1.0"),
            SimpleNamespace(metadata={"Name": "example"}, version="2.0"),
        ],
    )
    monkeypatch.setattr(quality_vbench.metadata, "version", lambda name: "1.0")
    assert quality_vbench.package_versions()["example"] == "1.0"
