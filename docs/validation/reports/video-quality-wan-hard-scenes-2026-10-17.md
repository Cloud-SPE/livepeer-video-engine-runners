# Standard Wan difficult-scene follow-up — 2026-10-17

This follows the [three-pair control review](video-quality-wan-a14b-2026-10-16.md#human-review--2026-10-17).
The operator explicitly resumed the work after intentionally stopping the earlier
trial to use the GPU. The focus remains visual quality on short matched clips.
Existing models, IDs, defaults and ownership modes are preserved.

## Workload and provenance

Three new standard Wan clips use seed 42: pouring hands, object relationships
and nighttime rain. Each is paired with its existing 480p LightWan reference
from the [resolution screening](video-quality-screening-2026-10-16.md). Prompt
text, seed input, 832×480 size, 81 frames and 16 FPS match exactly. No baseline
is regenerated, no uncertain prior run is resumed and no held-out scene is used.

These are selected development failures, not a representative random sample.
The test asks whether the standard recipe helps with extra hands, disappearing
objects and duplicated umbrellas. One seed per scene is a first screen; favorable
results require more seeds and held-out confirmation before promotion.

The candidate retains the [recorded standard recipe](video-quality-wan-a14b-2026-10-16.md#workload-and-recipe):
40 steps, BF16 experts, CFG scales 4/3, flow shift 12, noise boundary 0.875,
dense SageAttention 2 and lazy CPU block loading/module unloading. The negative
prompt remains empty. The reference retains its four trained NVFP4 steps and
sparse-attention recipe. This is a comparison of complete recipes, not an
isolated precision or step-count experiment.

All 82 served BF16 block/non-block checkpoint files were rehashed against their
preserved partition receipt: 57,154,191,488 bytes matched. Original, BF16 and
partitioned weights remain in external storage. No model was downloaded or
removed during this follow-up. Hash verification also primes file caches;
generation timing is not a cold-start benchmark.

The engine image remains
`sha256:7d3fe67ce806e6736d84566c788b9073b2452d64293c10b5c88826c0e3d6f013`,
with LightX2V source `8e86555809efd20138d3a4e1f937ee306cdf0ee0` and original
Wan assets at `c8c270b13ee05bfa474194ac9fb07a5868a97cea`. The CPU provider uses
commit `bd84def8e1f9` with the active-request health and shutdown corrections.
Its runner image is
`sha256:ac31e542b26a82fc6ab898147772b58e4c3051534fb775124c518c02ed27db4b`.
The staged archive also included uncommitted gallery/documentation work. Its
recorded archive and serving-file hashes distinguish the actual provider image
from later local gallery-tool changes.

Hardware is one reserved RTX 5090 with 32,607 MiB, driver 580.178.04 and about
91 GiB host RAM. The engine host-memory limit remains 72 GiB. The Python SDK
uses an isolated free node over private LAN. This is not paid-operation evidence.

## Shutdown correction and verification

The new regression reproduces shutdown while a real controller HTTP operation
continues replacing an engine after its client task is canceled. The old runner
shutdown failed with `controller is busy or requires recovery`. Managed shutdown
now waits for that operation, then confirms deactivation within a shared
120-second budget. Both root Compose files allow 150 seconds for runner stop.
Timeout preserves unknown engine state and raises an error rather than claiming
the GPU is released. A terminal controller error still permits verified cleanup.

The race test was observed failing before implementation. Deliberate mutations
also demonstrated that timeout/error-phase tests reject broken behavior. All
201 CPU tests, 33 Compose configurations and managed combined-catalog Docker
integration passed before the GPU deployment; managed test cleanup was verified.
The source and [deployment guide](../../guides/container-deployment.md#stop-restart-and-update)
describe the bound and its limitations. A controller that remains unavailable
still requires operator reconciliation; the fix is not an unconditional stop
guarantee under host/daemon failure.

After generation, the hardware check verified the owned idle engine's immutable
identity and full trusted launch policy before stopping it. It observed the
controller in `switching` and stopped the runner during replacement. Runner stop
and confirmation took 7.38 seconds, with runner exit code zero, no remaining
owned engine, and durable controller state disabled/idle with no recorded
containers. The controller then stopped and released its GPU lease. This is one
successful case, not a measured deadline guarantee for every startup/failure.

The seed selector was then verified with 202 full CPU tests passing. Its new test
was observed failing with two pairs instead of one before seed filtering was
implemented. Source plans and receipts remain unchanged when selecting clips.

## Generation and technical checks

All three new SDK requests delivered distinct checksum-verified MP4s. Each
decoded as 832×480, 81 distinct frames at 16 FPS (5.0625 seconds). No request was
retried. The reference clips are reused from their original completed receipts.

| Scene                | Reference delivery/inspection seconds | Candidate delivery/inspection seconds |
| -------------------- | ------------------------------------- | ------------------------------------- |
| Pouring hands        | 10.58                                 | 711.73                                |
| Object relationships | 10.53                                 | 685.48                                |
| Nighttime rain       | 10.67                                 | 690.33                                |

Matched medians are 10.58 and 690.33 seconds, approximately 65 times apart.
These include SDK delivery and local decoding/hashing, with prepared assets and
kernel/file caches. They do not establish cold-start behavior or latency guarantees.

Half-second telemetry recorded a 12,984 MiB GPU peak, zero observed engine OOM
kills and no sampling errors. The engine host-memory cgroup reached approximately
72 GiB, with file cache accounting for much of its memory. Sampled peak anonymous
memory was about 14.6 GiB and sampled peak file cache about 70.3 GiB. Those peaks
are not simultaneous quantities to add. This does not establish a lower minimum
host-memory requirement.

## Offline diagnostics

All six custom-input dimensions completed on the three saved candidate clips in
an isolated evaluator with network access disabled. The evaluator image remains
`sha256:2ba224881b4e4cb4cc0d00002da3a9ef4124bd4d80fe992da6bad736c58a0060`,
with VBench source `fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490`. Its source,
packages, settings, checkpoint hashes and cached-source hashes match the earlier
reference evaluation. Input checksums bind imported scores to the completed run.
The shared GPU lease excluded simultaneous managed serving/evaluation.

Means below use only the three matching reference prompt/seed clips, rather than
the full earlier screening set. Per-video imaging quality is divided by 100 to
match the pinned vendor's aggregate scale; original raw results remain intact.

| Diagnostic             | LightWan reference | Standard Wan candidate |
| ---------------------- | ------------------ | ---------------------- |
| Subject consistency    | 0.9645             | 0.9740                 |
| Background consistency | 0.9567             | 0.9624                 |
| Motion smoothness      | 0.9930             | 0.9953                 |
| Dynamic degree         | 0.3333             | 0.0000                 |
| Aesthetic quality      | 0.6427             | 0.5786                 |
| Imaging quality        | 0.7049             | 0.6510                 |

Higher consistency/smoothness accompanies lower aesthetic/imaging scores in this
sample. Dynamic degree detects motion above a threshold; it is not a quality
score, and zero does not mean a video is static. All decoded frames were distinct.
These dimensions do not establish correct anatomy, object counts, prompt fidelity
or usable output. No combined quality score or quality winner is inferred.

## Blind review and cleanup

The gallery contains exactly three prompt/seed-matched A/B pairs and six videos,
each appearing once. Experiment, prompt and seed filters select existing source
evidence without rewriting it. All six served video hashes matched, while
private key/operator paths returned 404. Model identities and scores are absent
from the served HTML, and the blinding key remains outside its root. The operator
has seen the references before, so randomized labels do not guarantee that the
clips cannot be recognized. Human preference and usability review are pending.

Cleanup verified the four service IDs/configuration fingerprints and network
identities recorded at startup, plus the recorded evaluator identity. It removed
five owned containers, four networks, three private CPU-image aliases, the
temporary controller-state volume and the exact private remote staging directory.
No daemon prune was used. Canonical prepared GPU images remain available.

All six protected external volumes retained their identities/creation times;
original, converted and partitioned model assets and caches remain. Existing
wallet/key files were not modified. Five unrelated running containers retained
their identities and start times. Evidence was archived without deployment
credentials. Local videos, receipts, metrics, source provenance, prior ratings
and the new gallery remain available. After cleanup, GPU use was 2 MiB at 0%
utilization; no trial resource remained on the GPU host.

## Current status

Generation, hardware recovery/shutdown verification, technical delivery checks,
all six offline diagnostics, gallery verification and owned-resource cleanup are
complete. Human review of the three pairs is next. No additional seeds, held-out
jobs or production profile promotion follow automatically from successful
decoding or metric values. Existing models and defaults remain unchanged.
