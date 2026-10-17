"""Reproducible operator video-quality benchmarks; generation is explicit."""

from dataclasses import asdict
import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
from html import escape
from itertools import combinations
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import time

from video_runners.catalog import load_catalog
from video_runners.contracts import JobRequest
from video_runners.tools.evidence import atomic_json, now, source_identity

ROOT = Path(__file__).resolve().parents[3]
DIMENSIONS = frozenset(
    {
        "subject_consistency",
        "background_consistency",
        "motion_smoothness",
        "dynamic_degree",
        "aesthetic_quality",
        "imaging_quality",
    }
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def indexed(rows):
    result = {}
    for row in rows:
        name = row["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
            raise ValueError("IDs must contain lowercase letters, digits, '.' or '-'")
        if name in result:
            raise ValueError(f"duplicate ID: {name}")
        result[name] = row
    return result


def validate_plan(benchmark):
    if (
        benchmark.get("schema_version") != 1
        or benchmark.get("kind") != "video-quality"
        or benchmark.get("id")
        != digest({key: value for key, value in benchmark.items() if key != "id"})
    ):
        raise RuntimeError("invalid or changed benchmark plan")
    ids = []
    for job in benchmark["jobs"]:
        if (
            job.get("id")
            != digest({key: value for key, value in job.items() if key != "id"})[:24]
        ):
            raise RuntimeError("invalid job identity in benchmark plan")
        ids.append(job["id"])
    if not ids or len(ids) != len(set(ids)):
        raise RuntimeError("benchmark plan must contain distinct jobs")


def plan(suite_file: Path, suite_name: str, *, experiments=()) -> dict:
    data = json.loads(suite_file.read_text())
    if data.get("schema_version") != 1:
        raise ValueError("unsupported suite schema_version")
    catalog_file = suite_file.parent / data["catalog"]
    prompt_file = suite_file.parent / data["prompts"]
    models, _ = load_catalog(catalog_file)
    prompts = indexed(map(json.loads, prompt_file.read_text().splitlines()))
    definitions = indexed(data["experiments"])
    suite = data["suites"][suite_name]
    selected = list(experiments or suite["experiments"])
    for values, available in ((selected, definitions), (suite["prompts"], prompts)):
        if (
            not values
            or len(values) != len(set(values))
            or any(x not in available for x in values)
        ):
            raise ValueError("selection must contain distinct known IDs")
    if any(name not in suite["experiments"] for name in selected):
        raise ValueError("experiment is not in the selected suite")
    seeds = suite["seeds"]
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("suite seeds must be nonempty and distinct")
    configured = {}
    for name in data.get("provenance", []):
        path = suite_file.parent / name
        configured[name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "content": json.loads(path.read_text()) if path.suffix == ".json" else None,
        }
    jobs = []
    for name in selected:
        experiment = definitions[name]
        spec = models[experiment["model"]]
        parameters = experiment.get("parameters", {})
        allowed = {
            "width",
            "height",
            "num_frames",
            "fps",
            "steps",
            "negative_prompt",
            "guidance_scale",
            "guidance_scale_2",
            "flow_shift",
        }
        if set(parameters) - allowed:
            raise ValueError(f"{name}: unsupported request controls")
        if spec.engine == "lightx2v" and set(parameters) & {
            "fps",
            "steps",
            "guidance_scale",
            "guidance_scale_2",
            "flow_shift",
        }:
            raise ValueError(
                f"{name}: LightX2V steps/fps require an engine configuration"
            )
        for prompt_id in suite["prompts"]:
            prompt = prompts[prompt_id]
            for seed in suite["seeds"]:
                request = asdict(
                    JobRequest.from_payload(
                        {
                            **parameters,
                            "prompt": prompt["prompt"],
                            "seed": seed,
                        },
                        spec.defaults,
                    )
                )
                request = {
                    key: value for key, value in request.items() if value is not None
                }
                if any(
                    request.get(key) == 0
                    for key in ("width", "height", "num_frames", "fps", "steps")
                ):
                    raise ValueError(
                        "video dimensions, frames, fps and steps must be positive"
                    )
                if request["negative_prompt"] and not spec.supports_negative_prompt:
                    raise ValueError(f"{name}: model does not support negative prompts")
                job = {
                    "experiment": name,
                    "model": spec.id,
                    "prompt_id": prompt_id,
                    "criteria": prompt.get("criteria", []),
                    "request": request,
                    "profile": {**asdict(spec), "command": list(spec.command)},
                    "configured_inputs_sha256": digest(configured),
                }
                jobs.append({"id": digest(job)[:24], **job})
    result = {
        "schema_version": 1,
        "kind": "video-quality",
        "suite": suite_name,
        "inputs": {
            "suite_sha256": hashlib.sha256(suite_file.read_bytes()).hexdigest(),
            "prompts_sha256": hashlib.sha256(prompt_file.read_bytes()).hexdigest(),
            "catalog_sha256": hashlib.sha256(catalog_file.read_bytes()).hexdigest(),
            "configured_files": configured,
        },
        "jobs": jobs,
    }
    return {"id": digest(result), **result}


@contextmanager
def locked(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (
        directory.is_symlink()
        or directory.stat().st_uid != os.getuid()
        or directory.stat().st_mode & 0o077
    ):
        raise RuntimeError(
            "run directory must be private and owned by the current user"
        )
    descriptor = os.open(
        directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("quality run is already running") from exc
        yield
    finally:
        os.close(descriptor)


async def generate(benchmark, directory, render, *, inspect=None, max_jobs=None):
    validate_plan(benchmark)
    with locked(directory):
        return await _generate(
            benchmark, directory, render, inspect=inspect, max_jobs=max_jobs
        )


async def _generate(benchmark, directory, render, *, inspect=None, max_jobs=None):
    if max_jobs is not None and (type(max_jobs) is not int or max_jobs < 1):
        raise ValueError("max_jobs must be positive")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    plan_file = directory / "plan.json"
    if plan_file.exists() and json.loads(plan_file.read_text()) != benchmark:
        raise RuntimeError("run plan changed; use a new run directory")
    atomic_json(plan_file, benchmark)
    state_file = directory / "receipt.json"
    state = (
        json.loads(state_file.read_text())
        if state_file.exists()
        else {
            "schema_version": 1,
            "kind": "video-quality",
            "plan_id": benchmark["id"],
            "source": source_identity(ROOT),
            "started_at": now(),
            "jobs": {},
        }
    )
    if state.get("plan_id") != benchmark["id"] or set(state["jobs"]) - {
        job["id"] for job in benchmark["jobs"]
    }:
        raise RuntimeError("receipt does not match the benchmark plan")
    if any(job["state"] != "completed" for job in state["jobs"].values()):
        raise RuntimeError(
            "run has an uncertain outcome; inspect it before further generation"
        )
    for job_id, entry in state["jobs"].items():
        path = directory / f"{job_id}.mp4"
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != entry["video"]["sha256"]
        ):
            raise RuntimeError("completed video checksum differs; refusing generation")
    state.update(status="running", outcome="unknown")
    atomic_json(state_file, state)
    submitted = 0
    for job in benchmark["jobs"]:
        if job["id"] in state["jobs"]:
            continue
        if max_jobs is not None and submitted >= max_jobs:
            break
        entry = {"state": "submitting", "started_at": now()}
        state["jobs"][job["id"]] = entry
        atomic_json(state_file, state)
        start = time.monotonic()
        path = directory / f"{job['id']}.mp4"
        try:
            delivery = await render(job, path)
            if inspect is None:
                from video_runners.tools.validate_gpu import verify_video

                inspect = verify_video
            video = inspect(path)
            for requested, observed in (
                ("width", "width"),
                ("height", "height"),
                ("num_frames", "frames"),
                ("fps", "fps"),
            ):
                expected = job["request"].get(requested)
                if (
                    expected is not None
                    and observed in video
                    and not math.isclose(video[observed], expected, rel_tol=0.001)
                ):
                    raise ValueError(
                        f"observed {requested} differs from requested value"
                    )
            entry.update(
                state="completed",
                video=video,
                delivery=delivery,
                latency_seconds=time.monotonic() - start,
                finished_at=now(),
            )
        except BaseException as exc:
            entry.update(state="uncertain", error_type=type(exc).__name__)
            state.update(status="failed", outcome="unknown")
            atomic_json(state_file, state)
            raise
        atomic_json(state_file, state)
        submitted += 1
    complete = len(state["jobs"]) == len(benchmark["jobs"])
    state.update(
        status="passed" if complete else "partial",
        outcome="verified" if complete else "verified_partial",
        finished_at=now(),
    )
    atomic_json(state_file, state)
    return state


def read_run(directory):
    benchmark = json.loads((directory / "plan.json").read_text())
    receipt = json.loads((directory / "receipt.json").read_text())
    validate_plan(benchmark)
    if receipt.get("plan_id") != benchmark["id"] or set(receipt["jobs"]) - {
        job["id"] for job in benchmark["jobs"]
    }:
        raise RuntimeError("receipt does not match the benchmark plan")
    return benchmark, receipt


def report(runs, output, *, experiments=(), prompts=(), seeds=()):
    records = [(directory, *read_run(directory)) for directory in runs]
    selections = {"experiment": set(experiments), "prompt_id": set(prompts)}
    requested_seeds = set(seeds)
    filtered = any(selections.values()) or bool(requested_seeds)
    for field, requested in selections.items():
        known = {job[field] for _, benchmark, _ in records for job in benchmark["jobs"]}
        if requested - known:
            raise ValueError(
                f"unknown report {field}: {', '.join(sorted(requested - known))}"
            )

    def selected(job):
        return all(
            not values or job[field] in values for field, values in selections.items()
        ) and (not requested_seeds or job["request"]["seed"] in requested_seeds)

    if filtered and not any(
        selected(job) and receipt["jobs"].get(job["id"], {}).get("state") == "completed"
        for _, benchmark, receipt in records
        for job in benchmark["jobs"]
    ):
        raise ValueError("no completed videos match report selection")
    output.mkdir(mode=0o700, parents=True)
    videos = output / "videos"
    videos.mkdir(mode=0o700)
    salt = secrets.token_hex(16)
    groups, copied = {}, set()
    for directory, benchmark, receipt in records:
        for job in benchmark["jobs"]:
            if not selected(job):
                continue
            entry = receipt["jobs"].get(job["id"], {})
            if entry.get("state") != "completed":
                continue
            source = directory / f"{job['id']}.mp4"
            if (
                hashlib.sha256(source.read_bytes()).hexdigest()
                != entry["video"]["sha256"]
            ):
                raise RuntimeError("review video checksum differs")
            blind_id = digest([salt, job["id"]])[:24]
            if blind_id in copied:
                continue
            copied.add(blind_id)
            destination = videos / f"{blind_id}.mp4"
            shutil.copyfile(source, destination)
            destination.chmod(0o600)
            group = (job["request"]["prompt"], job["request"]["seed"])
            groups.setdefault(group, []).append(
                {
                    "blind_id": blind_id,
                    "experiment": job["experiment"],
                    "model": job["model"],
                    "job_id": job["id"],
                    "run": str(directory),
                    "criteria": job["criteria"],
                    "sha256": entry["video"]["sha256"],
                }
            )
    pairs, cards = [], []
    for (prompt, seed), members in groups.items():
        ordered = sorted(members, key=lambda m: m["blind_id"])
        for sides in combinations(ordered, 2) if len(ordered) > 1 else [(ordered[0],)]:
            pair_id = digest([salt, [s["blind_id"] for s in sides]])[:16]
            pairs.append(
                {"id": pair_id, "prompt": prompt, "seed": seed, "sides": list(sides)}
            )
    pairs.sort(key=lambda p: p["id"])
    for pair in pairs:
        sides = pair["sides"]
        clips = "".join(
            f'<div><strong>{label}</strong><video controls loop playsinline preload="metadata" src="videos/{side["blind_id"]}.mp4"></video><label>Usable? <select data-side="{label}" onchange="save()"><option value="">Unrated</option><option value="yes">Yes</option><option value="no">No</option></select></label></div>'
            for label, side in zip("AB", sides)
        )
        criteria = "; ".join(sides[0]["criteria"])
        choices = (
            ("A", "B", "tie", "neither") if len(sides) == 2 else ("usable", "unusable")
        )
        options = "".join(
            f'<option value="{choice}">{choice}</option>' for choice in choices
        )
        cards.append(
            f'<article id="{pair["id"]}"><p>{escape(pair["prompt"])}</p><p class="criteria">Look for: {escape(criteria)}</p>'
            f'<section>{clips}</section><button onclick="playPair(this)">Play together</button> '
            f'<button onclick="pausePair(this)">Pause</button> '
            f'<label>Preference <select class="preference" onchange="save()"><option value="">Unrated</option>{options}</select></label>'
            '<p><label>What worked or failed <textarea oninput="save()"></textarea></label></p></article>'
        )
    report_id = digest([salt, [pair["id"] for pair in pairs]])[:24]
    script = """
const reportId = REPORT_ID;
function playPair(button) { for (const v of button.closest('article').querySelectorAll('video')) { v.currentTime = 0; v.play().catch(()=>{}); } }
function pausePair(button) { for (const v of button.closest('article').querySelectorAll('video')) v.pause(); }
function ratings() { return Array.from(document.querySelectorAll('article')).map(a => ({pair_id:a.id, preference:a.querySelector('select.preference').value, usability:Array.from(a.querySelectorAll('select[data-side]')).map(s=>s.value), notes:a.querySelector('textarea').value})); }
function save() { try { localStorage.setItem(reportId, JSON.stringify(ratings())); } catch(e) {} }
let saved=[]; try { saved=JSON.parse(localStorage.getItem(reportId) || '[]'); } catch(e) {}
for (const row of saved) { const a=document.getElementById(row.pair_id); if(a) { a.querySelector('select.preference').value=row.preference; a.querySelector('textarea').value=row.notes; a.querySelectorAll('select[data-side]').forEach((s,i)=>s.value=(row.usability||[])[i]||''); } }
function exportRatings() { const blob=new Blob([JSON.stringify({schema_version:1, report_id:reportId, ratings:ratings()},null,2)],{type:'application/json'}); const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download='ratings.json'; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
""".replace(
        "REPORT_ID", json.dumps(report_id)
    )
    html = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Video comparison</title><style>body{font:16px system-ui;margin:24px auto;max-width:1200px;padding:0 16px;background:#15171b;color:#eee}article{padding:20px;margin:24px 0;background:#25282e;border-radius:8px}section{display:flex;gap:16px}section>div{flex:1;min-width:0}video{display:block;width:100%;margin:8px 0}button,select,textarea{font:inherit;padding:8px}textarea{display:block;width:95%;min-height:45px}.criteria{color:#b8c2d3}@media(max-width:650px){section{display:block}}</style>"
        "<h1>Video comparison</h1><p>Review complete clips. Judge prompt fidelity, identity, anatomy, motion and visual detail. A/B identities are randomized. Export your ratings before sharing this folder.</p>"
        '<button onclick="exportRatings()">Export ratings</button>'
        + "".join(cards)
        + f"<script>{script}</script></html>"
    )
    (output / "index.html").write_text(html)
    (output / "index.html").chmod(0o600)
    key = {"schema_version": 1, "report_id": report_id, "pairs": pairs}
    if filtered:
        key["selection"] = {
            "experiments": sorted(experiments),
            "prompts": sorted(prompts),
        }
        if requested_seeds:
            key["selection"]["seeds"] = sorted(requested_seeds)
    atomic_json(output.with_name(output.name + ".key.json"), key)
    return {
        "report_id": report_id,
        "pairs": len(pairs),
        "videos": len(copied),
        "key_file": str(output.with_name(output.name + ".key.json")),
    }


def score(directory, results_file, evaluator_ref):
    if not re.fullmatch(r"[0-9a-f]{40}", evaluator_ref):
        raise ValueError("evaluator_ref must be an immutable VBench commit")
    with locked(directory):
        benchmark, receipt = read_run(directory)
        completed = {
            key: value
            for key, value in receipt["jobs"].items()
            if value["state"] == "completed"
        }
        if not completed:
            raise ValueError("there are no completed videos to score")
        for job_id, entry in completed.items():
            if (
                hashlib.sha256((directory / f"{job_id}.mp4").read_bytes()).hexdigest()
                != entry["video"]["sha256"]
            ):
                raise RuntimeError("score video checksum differs")
        raw = json.loads(results_file.read_text())
        results = raw.get("results", raw)
        environment = raw.get("evaluator", {})
        if environment.get("revision", evaluator_ref) != evaluator_ref:
            raise ValueError("evaluator revision differs")
        if environment and (
            raw.get("plan_id") != benchmark["id"]
            or environment.get("inputs_sha256")
            != {key: value["video"]["sha256"] for key, value in completed.items()}
        ):
            raise ValueError("evaluator plan or input checksum differs")
        if not results or set(results) - DIMENSIONS:
            raise ValueError(
                "only supported custom-input VBench dimensions may be imported"
            )

        def numeric(value):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("VBench scores must be finite numbers")
            return float(value)

        by_job = {
            key: {"sha256": value["video"]["sha256"], "metrics": {}}
            for key, value in completed.items()
        }
        aggregates = {}
        for dimension, (aggregate, rows) in results.items():
            aggregates[dimension] = numeric(aggregate)
            seen = set()
            for row in rows:
                job_id = Path(row["video_path"]).stem
                if job_id not in completed or job_id in seen:
                    raise ValueError(
                        "VBench results contain an unknown or duplicate video"
                    )
                seen.add(job_id)
                by_job[job_id]["metrics"][dimension] = numeric(row["video_results"])
            if seen != set(completed):
                raise ValueError("VBench results omit a completed video")
        stored = {
            "schema_version": 1,
            "plan_id": benchmark["id"],
            "evaluator": {
                "name": "VBench",
                "revision": evaluator_ref,
                "mode": "custom_input",
                "provenance": environment or "operator_asserted",
            },
            "source_sha256": hashlib.sha256(results_file.read_bytes()).hexdigest(),
            "dimensions": sorted(results),
            "missing_dimensions": sorted(DIMENSIONS - set(results)),
            "aggregate": aggregates,
            "scores_by_job": by_job,
        }
        atomic_json(directory / "scores.json", stored)
        return stored


async def sdk_render(job, path, discovery, signer):
    from video_runners.client import single_shot

    values = asdict(JobRequest.from_payload(job["request"], {}))
    args = argparse.Namespace(
        **values,
        model=job["model"],
        discovery=discovery,
        output=str(path.with_suffix("")),
    )
    async with asyncio.timeout(job["profile"]["job_timeout_s"] + 120):
        return await single_shot(args, signer or None)


def summarize(key, ratings):
    if (
        key.get("schema_version") != 1
        or ratings.get("schema_version") != 1
        or key["report_id"] != ratings["report_id"]
    ):
        raise ValueError("ratings belong to a different report")
    pairs = {pair["id"]: pair for pair in key["pairs"]}
    stats, votes, seen = {}, {}, set()
    for pair in pairs.values():
        for side in pair["sides"]:
            stats.setdefault(
                side["experiment"],
                {
                    name: 0
                    for name in (
                        "wins",
                        "losses",
                        "ties",
                        "neither",
                        "usable",
                        "unusable",
                        "conflicting_usability",
                    )
                },
            )
    for rating in ratings["ratings"]:
        pair_id = rating["pair_id"]
        if pair_id not in pairs or pair_id in seen:
            raise ValueError("unknown or duplicate report pair")
        seen.add(pair_id)
        sides = pairs[pair_id]["sides"]
        choice = rating.get("preference", "")
        allowed = (
            {"", "A", "B", "tie", "neither"}
            if len(sides) == 2
            else {"", "usable", "unusable"}
        )
        if choice not in allowed:
            raise ValueError("invalid review preference")
        usability = rating.get("usability", [""] * len(sides))
        if len(usability) != len(sides) or set(usability) - {"", "yes", "no"}:
            raise ValueError("invalid usability ratings")
        for index, side in enumerate(sides):
            row = stats[side["experiment"]]
            if len(sides) == 2 and choice:
                field = (
                    ("wins" if index == (0 if choice == "A" else 1) else "losses")
                    if choice in {"A", "B"}
                    else ("ties" if choice == "tie" else "neither")
                )
                row[field] += 1
            vote = usability[index]
            if len(sides) == 1 and choice:
                vote = "yes" if choice == "usable" else "no"
            if vote:
                votes.setdefault((side["experiment"], side["job_id"]), set()).add(vote)
    for (name, _), values in votes.items():
        field = (
            "conflicting_usability"
            if len(values) > 1
            else ("usable" if "yes" in values else "unusable")
        )
        stats[name][field] += 1
    for row in stats.values():
        decided = row["wins"] + row["losses"]
        assessed = row["usable"] + row["unusable"]
        row["paired_win_fraction"] = row["wins"] / decided if decided else None
        row["usable_fraction"] = row["usable"] / assessed if assessed else None
    return {
        "schema_version": 1,
        "report_id": key["report_id"],
        "experiments": stats,
        "scope": "Descriptive paired preferences; no significance claim. Conflicting usability votes are excluded from usable fractions.",
    }


async def sdk_generate(benchmark, directory, discovery, signer, max_jobs):
    from video_runners.client import runner_selector, SINGLE_SHOT_APP

    validate_plan(benchmark)
    if type(max_jobs) is not int or max_jobs < 1:
        raise ValueError("max_jobs must be positive")
    receipt = directory / "receipt.json"
    recorded = json.loads(receipt.read_text())["jobs"] if receipt.exists() else {}
    pending = [job for job in benchmark["jobs"] if job["id"] not in recorded][:max_jobs]
    for model in dict.fromkeys(job["model"] for job in pending):
        await runner_selector(
            discovery_url=discovery, app=SINGLE_SHOT_APP.format(model=model)
        )

    async def render(job, path):
        return await sdk_render(job, path, discovery, signer)

    return await generate(benchmark, directory, render, max_jobs=max_jobs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planner = commands.add_parser(
        "plan", help="Expand a suite without contacting services"
    )
    planner.add_argument(
        "--suite-file", type=Path, default=ROOT / "benchmarks/video-quality/suites.json"
    )
    planner.add_argument("--suite", default="pilot")
    planner.add_argument("--experiment", action="append", default=[])
    planner.add_argument("--output", type=Path, required=True)
    runner = commands.add_parser(
        "generate", help="Submit a bounded batch through the Python SDK"
    )
    runner.add_argument("--plan", type=Path, required=True)
    runner.add_argument("--run-dir", type=Path, required=True)
    runner.add_argument("--max-jobs", type=int, default=1)
    runner.add_argument(
        "--discovery", default="http://127.0.0.1:8937/discover-orchestrators"
    )
    runner.add_argument("--signer", default="http://127.0.0.1:8937")
    scorer = commands.add_parser(
        "score", help="Import VBench custom-input results for existing videos"
    )
    scorer.add_argument("--run-dir", type=Path, required=True)
    scorer.add_argument("--results-file", type=Path, required=True)
    scorer.add_argument("--evaluator-ref", required=True)
    reviewer = commands.add_parser(
        "report", help="Create a blind HTML gallery and a separate private key"
    )
    reviewer.add_argument("--run-dir", type=Path, action="append", required=True)
    reviewer.add_argument("--output", type=Path, required=True)
    reviewer.add_argument(
        "--experiment", action="append", default=[], help="Include this experiment ID"
    )
    reviewer.add_argument(
        "--prompt", action="append", default=[], help="Include this prompt ID"
    )
    reviewer.add_argument(
        "--seed", type=int, action="append", default=[], help="Include this seed"
    )
    summarizer = commands.add_parser(
        "summary", help="Unblind exported ratings and summarize preferences/usability"
    )
    summarizer.add_argument("--key", type=Path, required=True)
    summarizer.add_argument("--ratings", type=Path, required=True)
    summarizer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            value = plan(args.suite_file, args.suite, experiments=args.experiment)
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            atomic_json(args.output, value)
            print(json.dumps({"plan": value["id"], "jobs": len(value["jobs"])}))
        elif args.command == "generate":
            value = json.loads(args.plan.read_text())
            result = asyncio.run(
                sdk_generate(
                    value, args.run_dir, args.discovery, args.signer, args.max_jobs
                )
            )
            print(
                json.dumps(
                    {"status": result["status"], "completed": len(result["jobs"])}
                )
            )
        elif args.command == "score":
            result = score(args.run_dir, args.results_file, args.evaluator_ref)
            print(
                json.dumps(
                    {
                        "dimensions": result["dimensions"],
                        "missing": result["missing_dimensions"],
                    }
                )
            )
        elif args.command == "report":
            print(
                json.dumps(
                    report(
                        args.run_dir,
                        args.output,
                        experiments=args.experiment,
                        prompts=args.prompt,
                        seeds=args.seed,
                    )
                )
            )
        else:
            value = summarize(
                json.loads(args.key.read_text()), json.loads(args.ratings.read_text())
            )
            atomic_json(args.output, value)
            print(json.dumps(value))
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
