# Benchmark and review video quality

The operator quality harness runs explicit jobs through the existing Python SDK,
then evaluates saved clips and builds a blind review gallery. It starts no node,
signer, runner or model. Use the existing [provider deployment](container-deployment.md)
and [node/signer setup](node-deployment.md). Existing models and defaults are retained.
Larger profiles require separate hardware evidence before being called validated.

Best visual quality is the initial tuning objective; generation taking minutes is
acceptable. Automated metrics support human review. Successful decoding, file
size, FPS and changing frames do not establish perceptual quality.

## Files and authority

| Location                                                                 | Purpose                                                               |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------- |
| [Prompts](../../benchmarks/video-quality/prompts.jsonl)                  | Twenty mixed scenes with explicit visual criteria                     |
| [Suites](../../benchmarks/video-quality/suites.json)                     | Pilot, screening and confirmation jobs; seeds and request overrides   |
| [Evaluator pin](../../benchmarks/video-quality/evaluator.json)           | VBench source revision, mode and dimensions                           |
| [Quality command](../../src/video_runners/tools/quality.py)              | Plan, generate, import scores, report and summarize reviews           |
| [Standalone evaluator](../../src/video_runners/tools/quality_vbench.py)  | GPU evaluation in an isolated environment                             |
| [Evaluator Dockerfile](../../deploy/docker/quality-evaluator.Dockerfile) | Optional short-lived evaluation image; no additional Compose stack    |
| `artifacts/video-quality/`                                               | Ignored private plans, original videos, receipts, metrics and reviews |

Experiments reference existing public model IDs. Images, commands, mounts, GPU
assignment and model assets stay in the existing independently maintained
[catalog and policy sources](configuration.md). Suite files have no Docker launch
authority. Changing a pinned/configured input changes plan and job identities.
Keep service URLs and credentials outside tracked benchmark data.

## Plan without services

Run from the checkout using the locked environment:

```sh
uv run --locked python -m video_runners.tools.quality plan \
  --suite pilot --experiment sglang-current \
  --output artifacts/video-quality/sglang-plan.json
```

The plan contains the resolved request, catalog entry, input hashes and configured
pins. These describe requested/configured values, not proof of what an engine
applied. The receipt separately stores observed video properties and SDK provider
metadata. Model-specific engine logs/provenance remain useful when verifying a
new sampling control. A seed is repeatable input, not a guarantee of identical
latents across engines or bit-identical GPU output.

The pilot uses one prompt and seed. Screening uses eight prompts and two seeds
(16 clips per experiment). Confirmation uses twenty prompts and three seeds
(60 clips per experiment), including twelve scenes excluded from screening.
Reserve those additional scenes until confirmation; reviewing/tuning on them
turns them into development data rather than held-out evidence.

Select one active model's experiments for each plan. The harness does not switch
models or manage Docker; use the existing authenticated management workflow
between model batches. This preserves management-triggered switching and one
exclusive GPU per engine instance.

## Generate a bounded batch

The default connection is the local node signer's discovery/payment interface:

```sh
uv run --locked --group stub python -m video_runners.tools.quality generate \
  --plan artifacts/video-quality/sglang-plan.json \
  --run-dir artifacts/video-quality/sglang-pilot --max-jobs 1
```

`--group stub` supplies PyAV for decoding; it does not select a stub engine.
Override `--discovery` and `--signer` for the configured services. For an explicit
free development-node test, use its reachable discovery URL and `--signer ''`.
Direct routing requires no SSH tunnel or traditional go-livepeer process.

Generation defaults to one new job per invocation. Raise `--max-jobs` explicitly
for a larger batch. Discovery must advertise the requested apps before a
submission receipt is created. A mixed-model batch cannot proceed when its apps
are unavailable. Generation is sequential; there is no new serving queue.

Requests are checked against supported controls. OpenAI-style adapters carry
step count, FPS, negative prompt, guidance scales and flow shift where the model
supports them. LightX2V step count, FPS, guidance and shift are engine-config
settings, so the benchmark refuses those request overrides. Use a separately
prepared profile for such comparisons. Distilled checkpoints keep their trained
sampling recipe; more steps are not automatically a quality improvement.

Completed videos are decoded and hashed. Observed dimensions, frame count and
FPS are compared with requested values. Each run has a private plan and durable
receipt. Another invocation cannot concurrently submit the same run.

## Resume and investigate

Repeat the same generate command to continue a bounded run. Completed clips are
checksum-verified before skipping them. An edited plan, missing/corrupted clip or
uncertain job blocks further submission. A submission is checkpointed before the
SDK call, so a crash cannot silently turn into a duplicate generation.

An interrupted request may have finished on the provider. Inspect the receipt,
provider and engine before deciding what happened. The harness deliberately has
no force-retry flag. Preserve uncertain evidence; an investigated, explicitly
chosen new job belongs in a new run. Discovery failures caught by preflight have
not submitted a generation and need no job recovery.

Receipts and raw provider details stay private. Follow the
[validation evidence rules](validation-runs.md) before publishing results.

## Evaluate saved clips

Use the optional evaluator on the GPU host after generation. If the client is on
another machine, transfer only its selected run directory and return the result
JSON to that same client run. The evaluator needs neither payment keys nor access
to the runner's Docker API. It never submits generation work.

```sh
docker build -f deploy/docker/quality-evaluator.Dockerfile \
  -t livepeer-video-quality-evaluator:local .
docker volume create --label io.livepeer.video.persistent=true \
  livepeer-video-quality-cache
```

The optional image shares the pinned CUDA/PyTorch base used by vLLM. Evaluation
packages remain in a separate environment and serving images stay unchanged.
VBench is imported from an unmodified pinned Git checkout: upstream's packaging
requires a visible GPU even while building metadata. The worker verifies the Git
revision rather than pretending a GPU is available during image construction.

Stop the owned provider's runner, then controller, using the existing Compose/env
selection. This releases its GPU lease. Preserve external volumes. Initialize the
controller normally once before evaluation: its existing GPU lock file must be
present. Configure the reserved GPU and the deployment's shared lease volume:

```sh
QUALITY_RUN_DIR="$(realpath artifacts/video-quality/sglang-pilot)"
QUALITY_GPU_UUID=GPU-replace-with-reserved-uuid
QUALITY_GPU_LEASE_VOLUME=livepeer-video-gpu-leases
VBENCH_COMMIT="$(python3 -c 'import json; print(json.load(open("benchmarks/video-quality/evaluator.json"))["revision"])')"

docker run --rm --gpus "device=$QUALITY_GPU_UUID" --shm-size 4g \
  --cap-drop ALL --cap-add DAC_OVERRIDE --cap-add CHOWN \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$QUALITY_RUN_DIR,target=/work" \
  --mount type=volume,source=livepeer-video-quality-cache,target=/root/.cache \
  --mount "type=volume,source=$QUALITY_GPU_LEASE_VOLUME,target=/leases,readonly" \
  livepeer-video-quality-evaluator:local \
  --run-dir /work --output /work/evaluations/vbench-001/results.json \
  --evaluator-ref "$VBENCH_COMMIT" --gpu-uuid "$QUALITY_GPU_UUID" \
  --lease-directory /leases \
  --dimension subject_consistency --dimension background_consistency \
  --dimension motion_smoothness --dimension dynamic_degree \
  --dimension aesthetic_quality --dimension imaging_quality
```

Choose a new evaluation subdirectory each time. The worker exposes/checks one GPU
and locks the same existing lease inode as the controller. It refuses evaluation
while a cooperating controller holds that GPU. This cannot exclude unrelated GPU
applications, so the reserved-GPU requirement still applies.

Evaluator checkpoint downloads remain in the external quality-cache volume for
reuse. Results record input hashes, evaluator revision, package versions and
cached weight and downloaded Python/YAML source hashes. New output artifacts are returned to the input directory's
owner when using a rootful evaluation container. The two explicit capabilities
allow access to private run/lease files and returning output ownership; mount
only the selected run and these cache/lease volumes. Source clips are unchanged.

Import the returned scores without submitting another generation:

```sh
uv run --locked python -m video_runners.tools.quality score \
  --run-dir artifacts/video-quality/sglang-pilot \
  --results-file artifacts/video-quality/sglang-pilot/evaluations/vbench-001/results.json \
  --evaluator-ref "$VBENCH_COMMIT"
```

Only completed, checksum-verified clips may receive scores. Worker results must
match the plan and input hashes. Raw upstream VBench result JSON can also be
imported, with its provenance explicitly marked operator-asserted. Missing
dimensions remain missing. A partial evaluation is not a full quality pass.

These six dimensions use VBench `custom_input`, following its
[supported custom-video protocol](https://github.com/Vchitect/VBench). Scores on
this project's prompts are not leaderboard scores. Some upstream evaluator
components download moving-source checkpoints/code; retain the cache and compare
its recorded hashes as well as the VBench revision. A source pin alone does not
pin every evaluator asset. Compare metrics separately;
there is no invented overall quality score. Pair consistency/smoothness with
dynamic degree and human checks for the requested movement. Dynamic degree
measures detected motion rather than quality; a higher value can also reflect
unwanted movement or artifacts.

## Blind review and summarize

Create a new gallery from one or more completed runs:

```sh
uv run --locked python -m video_runners.tools.quality report \
  --run-dir artifacts/video-quality/sglang-pilot \
  --run-dir artifacts/video-quality/candidate-pilot \
  --output artifacts/video-quality/review-001
python3 -m http.server 8099 --bind 127.0.0.1 \
  --directory artifacts/video-quality/review-001
```

Open `http://127.0.0.1:8099/`. Matching prompt/seed clips form randomized A/B
pairs; single clips have usability review. Review whole videos for prompt
fidelity, identity/anatomy, motion and visual detail. Choose A/B/tie/neither,
optionally mark each clip usable/unusable, and record reasons. Export ratings
before sharing the gallery. Browser-local saved ratings are convenience storage;
the exported JSON is the review artifact.

The private blinding key is the sibling `review-001.key.json`, outside the served
directory. Share only the gallery when collecting blind feedback. Prompts are
HTML-escaped; model/provider identities, timings and scores are absent from the
blind page. A/B playback restarts both clips together; it does not make different
native durations/frame rates an identical workload.

After review, unblind the exported file:

```sh
uv run --locked python -m video_runners.tools.quality summary \
  --key artifacts/video-quality/review-001.key.json \
  --ratings /path/to/exported/ratings.json \
  --output artifacts/video-quality/review-001-summary.json
```

The summary reports wins/losses, ties/neither and the win fraction among decided
pairs. Usability counts distinct clips; conflicting votes on the same clip are
reported and excluded from the usable fraction. Small pilot counts are
descriptive, not statistically established improvements. Confirm promising
candidates with more prompts/seeds and independent review before promotion.

Keep native-profile comparisons separate from controlled parameter comparisons.
For a controlled test, hold prompt, seed, duration and encoding fixed except the
intended variable. Record latency, sampled peak VRAM/RAM and failures beside
quality; the existing provider-host telemetry helper can supply resource data.

## Cleanup and verification

Retain clips and ratings until the operator reviews the round. Stop any temporary
gallery server, evaluator and owned provider deployment afterward. Preserve
wallet/key files, model/engine caches, the quality-cache volume and shared GPU
lease data. Remove only verified owned test resources; never prune the daemon.

Routine checks test planning, control handling, resume, concurrency, score
binding and review aggregation with CPU fixtures. They use no GPU, Docker daemon
or funded signer. Actual quality and model-fit claims need dated evidence in the
[validation matrix](../validation/index.md). The
[execution plan](../plans/active/video-quality.md) tracks this work.
