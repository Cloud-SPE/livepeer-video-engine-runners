# Standard Wan A14B quality comparison — 2026-10-16

This experiment compares standard Wan2.2 T2V A14B with the existing LightWan
A14B NVFP4 reference. Both run through LightX2V. The objective is visual quality
on matched short clips; existing models, public IDs and defaults are retained.
The operator reviewed the three delivered comparisons on 2026-10-17: one win
each and one tie, with all six clips usable. This partial sample establishes no
consistent quality preference, and no production preset is promoted.

## Workload and recipe

The targeted set contains pouring hands, object relationships and nighttime rain,
plus walking fox and portrait turn as controls. Each uses seeds 42/123: ten new
candidate clips paired with ten existing 480p clips from the
[resolution screening](video-quality-screening-2026-10-16.md). Positive prompts,
seed inputs, 832×480 dimensions, 81 frames and 16 FPS are matched. No held-out
confirmation scene is used. Shared seeds do not guarantee identical latent noise
or bit-identical results across recipes.

| Control                  | Standard Wan candidate                               | LightWan reference                           |
| ------------------------ | ---------------------------------------------------- | -------------------------------------------- |
| Checkpoint               | Original Wan2.2 T2V A14B experts, cast to BF16       | Trained NVFP4 step-distilled experts         |
| Steps                    | 40                                                   | 4 trained steps                              |
| Classifier-free guidance | Enabled, scales 4 / 3                                | Disabled                                     |
| Flow shift               | 12                                                   | 5                                            |
| Expert switch            | Noise boundary 0.875                                 | Trained switch after two steps               |
| Self-attention           | Dense SageAttention 2                                | Dynamic sparse attention, sparsity ratio 0.9 |
| Cross-attention          | SageAttention 2                                      | SageAttention 2                              |
| Weight loading           | CPU block offload, lazy loading and module unloading | GPU experts, CPU text encoder                |
| Negative prompt          | Empty                                                | Omitted by the CFG-free adapter              |

This compares complete recipes. A preference difference cannot be attributed to
precision, step count, guidance or attention separately.

The engine image remains
`sha256:7d3fe67ce806e6736d84566c788b9073b2452d64293c10b5c88826c0e3d6f013`,
using LightX2V source `8e86555809efd20138d3a4e1f937ee306cdf0ee0`. The CPU provider
uses repository base `8ac60f5e182e560c31117cf6ae7500bb26dc0389` plus the recorded
runner health-monitor patch below. Hardware is one reserved RTX 5090 with
32,607 MiB, driver 580.178.04 and about 91 GiB host RAM. The trusted engine memory
limit is 72 GiB. SDK delivery uses an isolated free node over private LAN;
this is not new paid-operation evidence.

## Persistent preparation

Original experts come from `Wan-AI/Wan2.2-T2V-A14B` at
`c8c270b13ee05bfa474194ac9fb07a5868a97cea`. Their twelve source shards total
approximately 114.3 GB. Each source file's SHA-256 was checked against the pinned
Hub metadata. Existing matching tokenizer, text-encoder and VAE assets were reused.

Separate checkpoint copies cast floating tensors to BF16, matching the runtime's
`DTYPE=BF16`; nonfloating tensors retain their dtype. A further lossless partition
produces forty block files and one non-block file per expert. All 82 files were
checked against the BF16 shards for tensor names, shapes, dtypes and every tensor
byte. Source/output hashes and conversion provenance are retained privately.
Original shards, BF16 shards and partitioned copies all remain in external model
storage. Serving mounts those assets read-only and uses offline asset lookup.
The candidate retains the standard VAE and uses CPU text-encoder/VAE offload.

The block layout lets the pinned runtime use its bounded CPU/GPU staging buffers
instead of pinning whole expert weights. This is a loading change, without
another quantization or training change. It does not guarantee bit-identical
video generation across runs.

## Interrupted feasibility attempts

The initial whole-expert offload attempt reached the second expert. A transient
health-probe failure withdrew the runner's registrations while its GPU job was
active. The node consequently canceled the active request. Docker events record
the controller's subsequent SIGTERM/SIGKILL and removal of its owned engine;
exit 137 alone was not an OOM diagnosis for that attempt. No video was delivered.

The runner now preserves active registrations through a failed health response
or probe exception, while closing new admission until health recovers. Idle
withdrawal/recovery, job deadlines, explicit cancellation and uncertain-job reset
requirements remain. Both new regression cases were observed failing before
their respective fixes. All 198 CPU tests and combined managed CPU integration
passed afterward. The deployed runner source SHA-256 is
`63b0b82756bf835b2e7bd9912a757ec94284e24dc629971cc47710d79fa5701c`.
See the [current health behavior](../../guides/container-deployment.md#generate-inspect-and-switch).

A separate attempt with that fix retained its active request through probe loss,
but the whole-expert route exhausted the 72 GiB host-memory cgroup during the
second expert's load. Kernel evidence identifies the recorded owned container;
its status request subsequently timed out. GPU use was roughly 7.5 GiB, so this
was host RAM pressure rather than a demonstrated VRAM ceiling. The conservative
client receipts remain uncertain. Independent evidence establishes termination,
and their replacement engines were deactivated normally. Neither run was resumed.

The third attempt uses the byte-verified per-block layout and supported lazy
loading, with the same weights, sampling controls and memory limit. It has a
separate plan/run identity. No unknown generation is automatically resubmitted.

## Current delivery evidence

The lazy-loading feasibility request completed through the SDK. Its delivered
MP4 decoded as 832×480, 81 frames at 16 FPS: 5.0625 seconds, with 81 distinct
decoded frames. Submission, delivery and local inspection took 704.48 seconds.
This establishes one successful generation, not visual superiority or a latency
guarantee. Timing includes model loading within the request and reuses prepared
assets/kernel caches.

Three requests completed, taking 704.48, 694.46 and 690.94 seconds respectively:
both walking-fox seeds and portrait seed 42. All three delivered distinct,
checksum-verified 832×480 videos with 81 distinct decoded frames at 16 FPS.

The fourth request, portrait seed 123, was interrupted at step 20 of 40. Docker
events show SIGTERM followed by exit 0 and removal of the recorded engine;
the signal's caller is not established by those events. Health/status responses
were successful immediately beforehand. The client retains an uncertain receipt;
independent container events establish that the engine terminated. The six
remaining requests were not submitted.

The batch stopped on that error. Its immediate shutdown overlapped the runner's
engine-replacement operation, so deactivation returned a busy response rather
than completing. A separate host command was then observed stopping the
controller and replacement engine. On 2026-10-17, the operator confirmed that
the stop was intentional. No GPU work was restarted. This interruption is not
evidence of a new model-memory failure or a successful full-batch reliability check.
The remaining owned node/socket-proxy services were stopped after ownership and
image verification. No test service or managed engine remains running. Final
owned-resource cleanup is recorded below; protected external data is preserved.

Sampling recorded a GPU peak of 12,984 MiB and no observed engine OOM kills.
The host-memory cgroup reached its 72 GiB limit, with most sampled memory in file
cache and about 13.3 GiB peak anonymous memory. These are distinct measurements;
they do not establish a minimum host-RAM requirement. One telemetry read failed
after the engine's cgroup disappeared. Offline perceptual evaluation and the full
comparison were not completed before the intentional stop. The original
and derived model assets remain in persistent external storage.

## Review and validation limits

The preliminary gallery contains the three completed matched pairs: six videos,
each appearing once. It selects matching experiment/prompt IDs from the original
runs, verifies their plans/receipts and clip hashes, and preserves the original
evidence. The unmatched reference clip was removed from this private gallery;
the generated key/HTML and the derivation are preserved outside the served root.
All six served video hashes were checked over HTTP, and private key/operator
paths returned 404. No baseline is regenerated. The planned full set contains
twenty clips in ten comparisons; pouring hands, object relationships and rain
have no candidate results yet. All three available comparisons were reviewed,
and no new perceptual scores have been measured. The operator has already seen the reference clips, so
randomized labels do not guarantee that their identities cannot be recognized.
This is one reviewer's targeted development sample, not a general usable-output
rate or a statistically established quality improvement.

The six VBench custom-input dimensions are supporting diagnostics. A future
evaluation can reuse the pinned isolated evaluator and persistent quality cache
after the provider releases its shared GPU lease. Per-video imaging values need explicit
division by 100 when matching the pinned vendor's aggregate scale; other metrics
remain separate. Human usability and anatomy/object-permanence findings decide
whether this candidate deserves held-out confirmation.

## Human review — 2026-10-17

The ratings export matched the preliminary report key and covered all three
pairs, every preference and all six usability fields. There were no unknown,
duplicate or missing pairs. Source and served-video hashes matched their
completed receipts. Original ratings, notes and the unblinded analysis remain
private.

| Scene         | Seed | Preferred recipe            | LightWan usable | Standard Wan usable |
| ------------- | ---- | --------------------------- | --------------- | ------------------- |
| Walking fox   | 42   | Standard Wan BF16, 40 steps | Yes             | Yes                 |
| Walking fox   | 123  | LightWan NVFP4, 4 steps     | Yes             | Yes                 |
| Portrait turn | 42   | Tie                         | Yes             | Yes                 |

Each recipe has one win, one loss and one tie; no pair was marked neither.
Notes confirm stable legs, walking, fur and footprints in both fox recipes, and
stable identity, glasses, facial motion and skin detail in both portraits. The
notes give no distinguishing reason for the two fox preferences. They do not
establish a particular improvement in detail, precision or sampling.

Matched median SDK delivery/inspection time was 10.70 seconds for LightWan and
694.46 seconds for standard Wan, about 65 times longer. The three reference
observations ranged from 10.60 to 25.95 seconds, and the candidate from 690.94
to 704.48 seconds. These are descriptive timings from prepared deployments,
including the first requests; they are not latency guarantees.

Keep the existing LightWan reference and defaults. The standard recipe remains
experimental: this small control-scene sample shows no consistent preference
benefit despite its substantially longer generation time. It does not establish
equivalence or rule out benefits on other scenes. Pouring hands, object
permanence and umbrellas remain untested for this candidate, and held-out
confirmation remains unused. If the operator resumes this work, those observed
failure scenes are the useful next comparison. No additional generation or
duration work follows automatically from these ratings.

## Final cleanup — 2026-10-17

Cleanup first verified immutable image/container identities, ownership labels
and exited state for all nine trial containers. It then removed those stopped
containers, four empty owned networks, four private CPU-image aliases, the
temporary controller-state volume and the exact private staging directory.
No stop/start, forced container removal or daemon prune was used in this final
cleanup.

The operator's direct stop left controller state marked enabled/active despite
all associated processes having exited. That state was archived and its temporary
volume removed only after verifying and removing every associated stopped
container. No engine was started to reconcile it. The shutdown/replacement race
remains a [recorded recovery gap](../../plans/tech-debt.md).

All six protected external model/cache/lease/wallet volumes retained their
identities and creation timestamps. Canonical prepared GPU images and original,
BF16 and partitioned model assets remain available. Five unrelated running
containers retained their identities and start times. Existing host keys and
wallet files were not modified. Private videos, receipts, ratings and evidence
remain local, and the preliminary gallery remains available for review.
