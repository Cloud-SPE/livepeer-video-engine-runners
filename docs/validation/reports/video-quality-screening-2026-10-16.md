# LightWan resolution screening and duration probe — 2026-10-16

This follows the [six-clip pilot](video-quality-2026-10-16.md) using the committed
quality harness at `8ac60f5e182e560c31117cf6ae7500bb26dc0389`. All existing models,
public IDs, defaults and ownership modes remain available. No default is promoted
by this screening round.

## Initial blind review

One operator reviewed all fifteen pairwise comparisons of the six original
clips, then exported ratings matched to the gallery's private blinding key.
Those comparisons repeatedly reused six clips from one prompt and seed; they
are not fifteen independent generation samples.

| Pilot profile            | Wins | Losses | Ties | Neither | Usability observations       |
| ------------------------ | ---- | ------ | ---- | ------- | ---------------------------- |
| LightWan A14B NVFP4 480p | 4    | 0      | 1    | 0       | Usable in every appearance   |
| LightWan A14B NVFP4 720p | 4    | 0      | 1    | 0       | Usable in every appearance   |
| SGLang FastWan 832×448   | 1    | 2      | 0    | 2       | Conflicting yes/no votes     |
| SGLang FastWan 832×480   | 0    | 2      | 0    | 3       | Conflicting yes/no votes     |
| LightX2V Wan 1.3B        | 0    | 2      | 0    | 3       | Unusable in every appearance |
| vLLM Wan 5B              | 0    | 3      | 0    | 2       | Unusable in every appearance |

The two LightWan resolutions tied directly. Favorable notes concerned requested
walking direction, footprints, coherent limbs and convincing detail/color.
Other profiles showed failures in movement, direction, anatomy or appearance.
Conflicting repeated usability ratings are preserved rather than resolved by
assumption. Original notes/ratings remain private.

The previous automated imaging score favored the smaller LightX2V profile,
although its clip was consistently rejected. High smoothness and thresholded
motion scores also failed to establish prompt compliance or usability. Metrics
remain supporting diagnostics; there is no aggregate quality winner.

## Screening design

The existing `screen` suite selects eight prompts and seeds 42/123. Experiments
are only `lightwan14b-nvfp4` and `lightwan14b-720p`: 32 new generations and sixteen
matched prompt/seed A/B pairs. Workloads use the same four-step trained recipe,
81 frames and 16 FPS. Resolution changes from 832×480 to 1280×720. Identical seeds
are shared inputs, not proof of identical latent noise across resolutions.

Scenes cover a walking animal, portrait turn, pouring hands, a running person,
ocean waves, a camera orbit, object relationships and nighttime rain. The twelve
additional confirmation scenes remain held out. Review includes full-screen
inspection so preview scaling does not hide resolution differences.

The reserved GPU is an RTX 5090 with 32,607 MiB, driver 580.178.04; host RAM is
about 91 GiB. The prepared LightX2V image remains
`sha256:7d3fe67ce806e6736d84566c788b9073b2452d64293c10b5c88826c0e3d6f013`.
Model/asset/configuration pins are unchanged from the pilot. The trusted engine
host-memory limit is 32 GiB. The local Python SDK calls the isolated free node
orchestrator over private LAN, with managed runner/controller ownership.
No funded signer or paid-operation claim is involved.

All 32 screening requests completed and delivered distinct checksum-verified
MP4s. Decoding confirmed 81 frames at 16 FPS and the requested dimensions for
every clip. The blind gallery contains sixteen pairs; each source clip appears
once, reducing repeated usability votes. The completed operator review is
summarized below.

| Profile       | Verified clips | Minimum / median / maximum seconds |
| ------------- | -------------- | ---------------------------------- |
| LightWan 480p | 16             | 10.45 / 10.63 / 25.95              |
| LightWan 720p | 16             | 25.04 / 25.33 / 26.27              |

Timing includes SDK submission, delivery and local decoding/hashing after engine
readiness. Model/kernel caches were reused. These observations do not establish
cold-start times, latency guarantees or perceptual improvement.

## Screening human review

One operator exported all sixteen comparisons. The export matched the private
report key, with no missing or duplicate pairs. All 32 source and gallery video
hashes matched their completed generation receipts. Original ratings, notes and
the unblinded prompt/seed analysis are retained privately.

| Profile | Wins | Losses | Ties | Neither | Usable | Unusable | Unanswered |
| ------- | ---- | ------ | ---- | ------- | ------ | -------- | ---------- |
| 480p    | 2    | 1      | 9    | 4       | 11     | 3        | 2          |
| 720p    | 1    | 2      | 9    | 4       | 11     | 4        | 1          |

Preference and usability are separate fields. The three unanswered usability
fields are excluded from usable fractions: 11/14 for 480p and 11/15 for 720p.
One pouring comparison selects neither while explicitly marking the 720p clip
usable; its notes still describe extra hands. That disagreement is preserved,
not recoded. It is different from conflicting repeated usability votes, which
did not occur because each clip appeared once. These are descriptive results
from one reviewer, eight prompts and two seeds; they do not establish a
statistically reliable resolution advantage or general usable-output rate.

| Scene                | Seed 42 preference | Seed 123 preference | Review findings                                                                       |
| -------------------- | ------------------ | ------------------- | ------------------------------------------------------------------------------------- |
| Walking fox          | Tie                | Tie                 | Both usable; stable limbs, footprints and detail                                      |
| Portrait turn        | Tie                | Tie                 | Both usable; stable identity and facial detail                                        |
| Pouring hands        | Neither            | Neither             | Extra hands in both resolutions; pouring failure in one clip                          |
| Running person       | 480p               | Tie                 | Both usable; less convincing leg motion in one 720p clip                              |
| Ocean wave           | Tie                | Tie                 | Both usable; coherent waves, foam and texture                                         |
| Camera orbit         | Tie                | Tie                 | Both usable; stable motorcycle geometry and parallax                                  |
| Object relationships | Neither            | 480p                | Appearing/disappearing balls; only one clip explicitly usable                         |
| Nighttime rain       | 720p               | Neither             | Duplicated or spontaneously appearing umbrellas; preferred clip has no usability vote |

All twenty clips across fox, portrait, running, waves and orbit received usable
votes. Difficult interactions and object permanence account for the rejections.
The single 720p preference still mentions an appearing umbrella, so a preference
win alone does not establish an acceptable output. Higher resolution did not
consistently fix anatomy, object count or temporal continuity. Its slightly
higher mean imaging score likewise did not translate into more human preference
wins.

Keep both profiles and existing defaults. The 480p profile is a practical
reference for the next controlled experiments: its median delivery time was
about 2.4 times shorter, with no observed consistent preference benefit from
720p. Best visual quality remains the priority; speed alone does not choose a
winner. Test candidate model/recipe changes against the pouring, object and
umbrella failures, using unchanged prompts/seeds and blind review. Preserve the
trained four-step recipe in this resolution comparison. Use the held-out scenes
only for subsequent confirmation. The 10/15-second examples still require their
own whole-clip visual review; these screening ratings do not cover them.

## Continuous duration ladder

The longer-output exploration prioritizes continuous generation, followed by an
edited sequence. Separate fox/seed-42 jobs used the same model, 832×480 resolution,
16 FPS and four-step recipe; only frame count changed. These duration examples
are outside the resolution-screening gallery and are not additional independent
scene coverage.

| Target     | Requested frames | Result                                     | SDK delivery/inspection seconds |
| ---------- | ---------------- | ------------------------------------------ | ------------------------------- |
| 10 seconds | 161              | 10.0625 s MP4, 161 distinct decoded frames | 21.17                           |
| 15 seconds | 241              | 15.0625 s MP4, 241 distinct decoded frames | 32.45                           |
| 20 seconds | 321              | Failed: CUDA out of memory                 | No delivered clip               |
| 30 seconds | 481              | Not submitted after the failed step        | —                               |

The 20-second task failed inside dynamic sparse self-attention while allocating
an output tensor (`torch.empty_like(q)`), before VAE decoding. The error requested
1.21 GiB with 483.75 MiB free, reporting 30.05 GiB allocated by PyTorch and roughly
151 MiB reserved but unused. `expandable_segments:True` was already configured.
This is observed capacity pressure in this recipe, not proof of a universal
model/GPU duration ceiling. VAE tiling alone would not address this particular
attention allocation; model/expert offload or a different attention/memory recipe
needs a separate experiment. Lower spatial resolution is another tradeoff.

The conservative client receipt retains an uncertain outcome; independent engine
logs establish the terminal CUDA failure. No generation was retried. The runner
replaced its owned engine afterward, and normal shutdown removed the replacement.
No post-reset generation was run, so this is not a new rendering-recovery pass.

Successful duration outputs establish native generation and delivery, not
whole-clip visual quality. Review sustained motion, identity/anatomy and drift
through the last frame. A compatible I2V/V2V/progressive checkpoint plus explicit
reference-media handling is a later route to conditioned continuation; repeated
persistent jobs currently do not carry that context automatically.

Duration output SHA-256 values (10 seconds, then 15 seconds):

```text
08286fee7d9246da1804e86f6333d2f1c992fe5f12524f1bda310de2f4e48a9e
4e493b33dd76070b3ce93b00f7e70ead1dec792416e040784fd15c7ca35f1dbd
```

## Edited 30-second sequence

Six separately generated 480p screening clips (animal, portrait, pouring hands,
running person, waves and nighttime rain; seed 42) were concatenated and encoded
with FFmpeg 6.1.1, libx264 CRF 18, yuv420p and 16 FPS. The output is trimmed to
480 frames: exactly 30 seconds at 832×480. All 480 decoded frames were distinct.
Source hashes, shot order, exact command and output inspection remain in the
private assembly receipt. This demonstrates a sequence with cuts, not continuous
30-second generation or conditioned extension. No additional inference was needed.

Montage SHA-256: `c326c993a65a5792614b29c8979c5b2e51d86080ce61855c2d2e22c4e5a50d79`.

## Offline evaluation and memory evidence

All 32 screening clips and both successful duration clips completed all six
VBench dimensions with pinned evaluator revision
`fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490`, custom-input mode and imaging
preprocessing `longer`. The evaluator image remained
`sha256:2ba224881b4e4cb4cc0d00002da3a9ef4124bd4d80fe992da6bad736c58a0060`.
It ran with Docker networking disabled and reused the external quality-cache
volume. Worker results matched plans and clip hashes during import. The failed
20-second job received no scores.

The following are means over sixteen screening clips per resolution:

| Profile | Subject consistency | Background consistency | Motion smoothness | Dynamic degree | Aesthetics | Imaging |
| ------- | ------------------- | ---------------------- | ----------------- | -------------- | ---------- | ------- |
| 480p    | 0.9594              | 0.9623                 | 0.9892            | 0.3750         | 0.6422     | 0.7081  |
| 720p    | 0.9546              | 0.9633                 | 0.9877            | 0.5000         | 0.6343     | 0.7209  |

Pinned VBench emits per-video imaging scores in MUSIQ's raw scale and divides the
aggregate by 100. The analysis divides per-video imaging values by 100 before
averaging, matching that aggregate scale; other values are unchanged. Original
vendor results are retained. Dynamic degree is a thresholded motion diagnostic
(6/16 versus 8/16 clips), not a usable-quality rate. The small mixed differences
in these custom-prompt metrics do not establish a winner or significance.

Host telemetry sampled approximately every 0.5 seconds:

| Stage                | Sampled peak GPU MiB | cgroup OOM kills |
| -------------------- | -------------------- | ---------------- |
| 32 screening jobs    | 32,106               | 0                |
| 10-second job        | 27,866               | 0                |
| 15-second job        | 31,268               | 0                |
| Failed 20-second job | 31,626               | 0                |

The screening peak left only 501 MiB below the device's reported capacity. GPU
samples can miss short peaks. Jobs share a loaded engine and allocator state;
these are observed stage maxima, not minimum VRAM requirements. Its cgroup
lifetime peak was 18,020,257,792 bytes, including startup and file cache across
stages. A CUDA allocation failure does not increment the host cgroup OOM-kill
counter. No sampling errors were reported for these recorded stages.

## Verification and cleanup

Runtime code and shipped model/default definitions were unchanged for this round.
The committed harness CI passed at `8ac60f5`; documentation/evidence additions
receive local navigation/configuration/format checks. Original clip hashes were
checked again when building the review gallery, importing metrics and assembling
the montage. The gallery has sixteen pairs and 32 distinct source-video hashes.
HTTP checks confirmed gallery/video/example delivery and refused the private
blinding-key path. The operator completed the sixteen-pair screening review and
its export matched the report key; longer-example visual review remains pending.

Cleanup verified the recorded container IDs, model ownership, immutable image
references, network IDs and an empty/disabled controller journal. It removed all
eight remaining owned service/evaluator containers, four networks, private image
aliases and the newly created temporary controller state. Private remote staging
was deleted. Canonical prepared images, external model/HF/engine/evaluator caches,
shared GPU lease data, wallet data and existing keys remain; unrelated services
were unchanged. GPU usage returned to 2 MiB. Private videos, metrics, failure
evidence and the local review server remain for the operator's review.
