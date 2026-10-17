# Video quality harness and larger-model trials

## Agreed scope

Preserve every existing model, public ID, default and deployment mode. Add a small
operator benchmark alongside the existing validation tools. Best visual quality
takes priority over generation latency; generation taking minutes is acceptable.
Use a mixed prompt suite initially. The operator reviews blind moving-video
comparisons and chooses useful presets. Automated scores support that judgment.

Use the existing Python SDK, optional local node signer and provider deployment.
Keep the existing production/development Compose entry points. Model launch
authority remains in the trusted controller catalogs; benchmark data never
supplies Docker commands, mounts or launch policies.

## Sequence and completion evidence

1. Add versioned prompts/suites, deterministic plans and configuration provenance.
2. Add bounded sequential generation with durable per-job records. Resume skips
   checksum-verified completed clips and refuses unknown outcomes. A changed plan
   cannot silently reuse another run's evidence.
3. Add offline technical inspection, an explicit VBench evaluator interface and
   a blind HTML review gallery with exportable ratings. Keep evaluator packages
   separate from inference/runtime dependencies. Show missing perceptual scores
   explicitly; decoding and frame differences are not perceptual quality scores.
4. Verify CPU behavior, packaging, documentation and existing deployments.
5. Run a small 5090 baseline/pilot through the SDK. Test a memory-saving Wan A14B
   recipe early, then a LightX2V larger-model candidate if compatible. Add reusable
   profiles only with pinned assets, matching independent launch policy and fresh
   hardware evidence. Preserve the existing entries and defaults.
6. Retain videos locally until reviewed. Remove owned test deployments and private
   staging resources; preserve model/cache volumes, wallets, keys and accounting.
   Publish only generic technical summaries in this repository.

## Behavioral test list

- [x] A plan expands selected prompts, seeds and experiments reproducibly.
- [x] Invalid, duplicate or unsupported controls fail before submitting work.
- [x] Interrupted/uncertain work is never automatically generated again.
- [x] Completed evidence is checked before skipping it on resume.
- [x] Concurrent invocations cannot submit the same run twice.
- [x] Reports blind experiment identity, escape prompt content and export ratings.
- [x] Scores identify evaluator/version and distinguish missing from measured.
- [x] Existing models/defaults remain present; new profiles have matching pins.

## Resource and evidence boundaries

Suite definitions and instructions are tracked; raw videos, private provenance,
receipts and reviews live in ignored per-run artifact directories. Connections,
signer URLs and credentials are operator inputs, not benchmark fixtures. GPU and
paid work are explicit operator invocations, separate from ordinary CPU CI.
Sampling controls are recorded as requested/configured/observed where supported;
the harness must not label a requested value as confirmed engine behavior.

The provider remains one exclusive GPU per engine instance. Existing model
switching coordinates lifecycle. A lock on a client host does not reserve a
remote GPU against unrelated applications. No daemon pruning or automatic
resubmission is permitted.

## Progress

The harness and six-clip 5090 pilot are implemented. Existing models/defaults
and Compose entry points are retained. LightWan A14B NVFP4 is the one added
profile, with offline preparation and real SDK delivery at 480p and 720p. Failed
full-precision/offload recipes remain private trials, not new supported profiles.
The [dated report](../../validation/reports/video-quality-2026-10-16.md) records
workloads, measured scores, startup failures and validation limits.

Generation, resume/concurrency, score binding, blinding and review aggregation
have CPU regression coverage (192 final tests). Both managed combined-catalog and bundled CPU
integration passed, as did all 33 Compose configurations and fresh wheel
installation outside the checkout. The evaluator was built and measured all six
custom-input dimensions on all six saved clips with persistent cached assets.

The initial and sixteen-pair resolution-screening operator reviews are complete;
both exported ratings matched their respective report keys. Screening found nine
ties, two 480p wins, one 720p win and four neither selections. Anatomy and object
permanence remain the main failures. No default or general quality winner is
promoted. Target those failures in controlled candidate comparisons, then use
held-out confirmation of promising candidates. No new paid-operation claim
follows from this free SDK pilot.

Owned hardware-test containers, private staging and temporary resource aliases
are removed. External models/caches, wallet/key data and reusable prepared images
remain; private review clips and evaluator results are retained.

## Resolution screening follow-up

The operator's initial blind review preferred both LightWan resolutions over the
other tested clips and tied 480p against 720p. The authorized follow-up used the
existing screening suite: eight prompts × two seeds × two resolutions, followed
by sixteen matched A/B comparisons. Separate 480p duration jobs delivered 161 and 241 frames (roughly ten and
fifteen seconds). A 321-frame request failed with CUDA out-of-memory; the ladder
stopped there without submitting the 481-frame request.
See the [screening report](../../validation/reports/video-quality-screening-2026-10-16.md)
for evidence and the [duration discussion](../../guides/video-quality.md#longer-video-clips)
for longer-output options. Existing models/defaults remain intact.

Earlier longer-output exploration prioritized a continuous shot, followed by an edited
sequence. The successful continuous probes kept the current recipe at 480p. A separate 30-second montage reuses six generated shots; it is evidence
for assembly only, not continuous generation or conditioned clip extension.

All 32 screening generations completed with distinct verified videos, and all six
VBench dimensions were measured offline on those clips and the two successful
longer clips. Sixteen-pair operator review is complete and its per-scene findings
are recorded in the screening report; whole-clip longer-output review remains
pending. The 20-second native
request failed in sparse attention; it was not retried and no native 30-second
request was submitted. The edited 30-second montage passed decoding checks.
The temporary GPU stack and remote staging are removed; the local review gallery
and private evidence remain available.

## Standard Wan quality comparison

The next authorized experiment compares the current LightWan 480p reference with
standard non-distilled Wan2.2 T2V A14B through the pinned LightX2V runtime. Start
with one SDK feasibility request; expand only after verified generation and
delivery. The target batch contains pouring hands, object relationships,
nighttime umbrellas, walking fox and portrait turn, with seeds 42/123: ten new
clips paired with their ten existing 480p references. Prompt text, seed inputs,
832×480 dimensions, 81 frames and 16 FPS remain matched. Held-out scenes stay
unused until confirmation.

The candidate uses its standard 40-step CFG recipe with BF16 weights, dense
SageAttention and supported CPU block offload/module unloading. The reference
retains its trained four-step NVFP4 sparse-attention recipe. This compares whole
recipes; it cannot attribute a preference difference to step count, precision or
attention alone. Negative prompts remain empty in this comparison.

Stage both original expert checkpoints at a pinned revision in external model
storage, then make separate BF16 checkpoint copies using the same cast as the
runtime. Retain source/output hashes and conversion provenance. Originals remain
available; derived files also persist for reuse. Bound preparation and serving
memory, record host/GPU telemetry, and run inference with offline asset lookup.
The previous failed vLLM loading attempts do not establish LightX2V feasibility.

Original expert downloads and separate BF16 copies are prepared and verified in
external model storage. The initial feasibility request was interrupted when a
transient engine health-probe loss withdrew registration during active GPU work;
the node canceled its request and the controller terminated the owned engine.
No video was delivered. The uncertain client receipt and independent termination
evidence are preserved rather than resumed.

The runner now preserves registrations during active GPU work while refusing new
admission on failed health. Two regression cases were observed failing before
their respective fixes; all 198 CPU tests and combined managed CPU integration
passed afterward. A separate feasibility run using that recorded runtime patch
with the same model recipe encountered a confirmed host-memory cgroup OOM at
72 GiB while loading the second expert. Lossless per-block BF16 checkpoint
partitioning enables the pinned runtime's supported lazy-loading path. That path
delivered three verified 81-frame clips through the SDK in approximately
691–704 seconds each. Docker SIGTERM interrupted the fourth request; the operator
subsequently confirmed that the stop was intentional. No GPU work was restarted.
Six planned requests remain unsubmitted. See the
[standard Wan trial](../../validation/reports/video-quality-wan-a14b-2026-10-16.md)
for exact recipes and evidence. The operator reviewed all three delivered pairs:
one win each and one tie, with all six clips usable. This control-scene sample
shows no consistent preference benefit for the standard recipe, whose matched
median delivery time was about 65 times longer. Hands, object relationships and
rain were untested for the candidate at that checkpoint; existing defaults were
retained. The subsequent follow-up is recorded below.
Review-gallery filters select existing clips without rewriting their plans or
receipts. No new perceptual scores were measured after the stop. The remaining
owned test deployment and private remote staging have been removed, preserving
external data and local review evidence. Any further GPU comparison needs a new
explicit operator invocation.

The operator subsequently resumed steps 1–4. The managed-shutdown correction is
committed at `bd84def`, with 201 CPU tests, 33 Compose configurations and managed
combined-catalog integration passing. A new bounded batch tests seed 42 on hands,
object relationships and rain against existing references. The 82 served model
files were rehashed without downloading or removing models. See the
[targeted follow-up](../../validation/reports/video-quality-wan-hard-scenes-2026-10-17.md)
for provider provenance, delivery, hardware shutdown, evaluation, review and
cleanup evidence. The gallery tool now supports selecting seeds as well
as experiments/prompts without changing source plans or receipts.

All three difficult-scene generations are complete and technically verified.
The hardware check observed controller replacement before runner shutdown and
confirmed exit zero, no owned engine and disabled/idle controller state in
7.38 seconds. Six offline diagnostics completed with matching evaluator
provenance. The verified gallery contains three pairs/six clips. Human review
preferred standard Wan for objects and rain, and LightWan for pouring. All three
candidate clips were marked usable; the reference has one usable, one unusable
and one unanswered vote. The preferred pouring reference still has an extra
hand, so anatomy remains unresolved. Final owned deployment/staging cleanup
passed with protected data and unrelated workloads unchanged. The gallery selector is committed in
`3d34d8c`, and the full CPU suite has 202 passing tests. Keep the candidate
experimental until further seeds and held-out confirmation justify a supported
operator profile. The proposed next step repeats objects and rain with another
matched seed and unchanged recipes, then confirms any repeated benefit on unused
scenes. Hands need separate investigation. No further generation follows
automatically from these scene-specific preferences.
Duration exploration and longer-example review are deferred at the operator's
request. The active objective is higher visual quality on matched short clips.
Preserve all existing models/defaults and protected external data;
remove only the temporary owned deployment when the trial finishes.
