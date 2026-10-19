# vLLM startup wait correction — October 19, 2026

The operator approved a targeted fix and free RTX 5090 validation of the
intermittent startup/output timeout. Existing models, request defaults, adapters,
ownership modes and deployment entry points remain. Paid/public acceptance and
quality work remain deferred.

## Cause and change

The previous vLLM image hardcoded a 30-second asynchronous-output wait. Its
synchronous warmup uses that same bound. Setting an environment variable or
raising the runner/controller's startup limit could not extend the engine's
internal wait. The queued work includes GPU computation before the output copy,
so a healthy slow step can exceed it.

The official [upstream fix](https://github.com/vllm-project/vllm-omni/commit/f09bdcbc7dc94827e76d4e9479674639be6ac442)
adds `VLLM_OMNI_ASYNC_OUTPUT_TIMEOUT`, defaults it to 600 seconds and uses it at
both wait sites. This repository now pins the official stable **v0.30.0 amd64**
image, which includes that fix:

- Previous: `vllm/vllm-omni@sha256:5cba1538c6f8ee81e8bea6708c24e68d7b2640f466a9fbf2ef15e68f2168b48b`.
- Selected: `vllm/vllm-omni@sha256:b09c9eab7d2e30817208de92ccb482756d13d4339377d7cc4c4ce9f47bf04174`.
- Stable source: `a8576ccb725c4e21cd13c3eb5f9a546b21149d2b`.
- Shipped `diffusion_engine.py` SHA-256: `42bb0c5b0223d5c24389948f73588d06e3813843d6c1f5b3c4e6632c6c7c9c51`, matching the immutable release source.

Both trusted vLLM profiles explicitly set the wait to 600 seconds. The engine
manifest, generated combined policy and retained bundled Dockerfile use the same
image. The bundled recipe also sets the environment; external deployments remain
operator-owned. The [deployment guide](../../guides/container-deployment.md#vllm-omni-output-wait)
explains the separate output/startup/job/drain limits. No engine source patch,
new image build, registry publication or custom GPU wrapper is involved.

## Regression evidence

The new [prepared-image probe](../../../tests/e2e/vllm-async-wait.py) extracts the
actual synchronous warmup wait and resolver from each prepared image without
importing the engine's GPU dependencies. With the environment set to 600, it
exercises a modeled Future that becomes ready at 31 seconds:

| Image               | Effective wait | Outcome             |
| ------------------- | -------------- | ------------------- |
| Previous pin        | 30 seconds     | Failed, as expected |
| Selected stable pin | 600 seconds    | Passed              |

The failing result was observed before changing the pins. This checks the actual
wait policy; it does not perform a delayed GPU warmup or recreate every cause of
an intermittent startup failure. The probe runs offline, read-only, without a
GPU or implicit pull. Its command belongs to the explicit
[Docker verification tier](../../reference/checks.md#prepared-vllm-image-wait-policy).

## Hardware configuration and delivery

The free test uses one RTX 5090, driver `580.178.04`, the production provider
Compose entry point and a private temporary free `livepeer/node` overlay. The
published CPU runner/controller/model-tools are from
`9d8452c03ff38f50098cd2f4cf4eb06ce7b8d0fd`; installed runner package hashes match
the checkout. The node source remains
`08081dbda0f4f7b56e362e3af4b6965bfa1b73a4`. The deployed trusted catalog matches
the proposed checked-in combined policy apart from its explicit local-image
allowance. CPU images were transferred without copying registry credentials.

The selected official engine was pulled by digest. Existing model and compiler
volumes were reused with offline model loading; no model download or cache reset
was performed. Wan 5B weights remain at
`b8fff7315c768468a5333511427288870b2e9635`. The existing CPU offload and VAE tiling
flags work with the selected image. SDK discovery, requests and media use direct
LAN HTTP, with SSH for management only; no signer, key mounts, paid request,
tunnel or legacy node was used.

At the unchanged **832×480, 49 frames, 24 FPS, 30 steps** default:

| Delivery           | Decoded videos | Request time, excluding engine startup |
| ------------------ | -------------- | -------------------------------------- |
| Single-shot        | 1              | 33.54 seconds                          |
| Persistent session | 2              | 50.72 seconds total                    |

All three MP4s decoded fully with 49 unique frames each. Seed 42 is identical
between single-shot and the first session clip, SHA-256
`1b43af926c30d5466ba3978d2e887dea5310b301bd70a0a460ac9850aec9252d`.
This differs from the prior engine's output for the same seed. Sampled frames
show a recognizable, consistent fox/scene; this is a basic corruption check, not
human quality acceptance. No quality ranking or duration defaults changed.
Client-host inference peak-memory telemetry was not collected.

## Startup and lifecycle checks

The initial complete stack readiness took 68.14 seconds. Two more vLLM starts
after switching to LightX2V passed in 48.27 and 43.27 seconds, including the
replacement's readiness check. These use saved caches, not a clean-compilation
benchmark. Deliberate idle loss of the verified owned vLLM container recovered
to registered readiness in 50.50 seconds, followed by a fresh decoded 49-frame
video; the original container was absent.

The following cases also passed against the new vLLM pin:

| Case                                               | Observation                                                                                    |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Graceful switch during a vLLM job                  | Complete 49-frame delivery before LightX2V readiness; 59.32 seconds including replacement load |
| Normal switch during a 200-step, 81-frame vLLM job | HTTP 409 after 120.35 seconds; job, engine and registrations unchanged                         |
| Explicit force after refusal                       | Client terminated, old engine absent and LightX2V ready; 49.01 seconds for the complete check  |
| Fresh request after force                          | Complete 81-frame LightX2V video                                                               |
| Shutdown during a new vLLM job                     | Client terminated, owned engine absent; 34.06 seconds                                          |

The complete window produced **six fully decoded videos**: five vLLM videos
and one LightX2V video. The two deliberately interrupted requests produced no
completed MP4 and were not replayed. Ten engine lifetimes were captured, six
using the new vLLM image. Failed-start rollback was not repeated against this
new image. SGLang inference was unchanged and not repeated; earlier cases are
recorded in the [acceptance evidence](operator-acceptance-2026-10-18.md#active-work-switching-and-shutdown).

## Cleanup

Verified engine deactivation completed before removing the four temporary
services, owned networks, disposable controller-state volume, temporary CPU tags
on both hosts and remote staging directory. The startup-log followers and both
validation lease holders exited. No owned test container/network or GPU compute
process remained; GPU memory returned to **2 MiB**.

All five unrelated container fingerprints, seven original network fingerprints
and 29 preexisting volume fingerprints matched. The 119 regular weight files
recorded before this window and the additional 44 cached weight paths from the
prior validated inventory retained their sizes and modification times. Existing
wallet/key files were never opened or mounted. Model/compiler caches, the shared
lease volume and prepared upstream engine images remain for operator reuse,
including the prior vLLM pin for rollback. Private local evidence keeps clips,
redacted logs and resource fingerprints; credentials and unrelated raw container
configuration were not copied into the repository.

## Repository verification

The fast checks passed **302 CPU tests** with the 34 existing aiohttp warnings;
all **37 Compose configurations** resolved. Black, Ruff, pre-commit formatting,
configuration generation, documentation links/index and import boundaries passed.

## Scope

This fixes the identified hardcoded output-wait limitation. It is not proof that
all startup failures or timing limits are resolved. Empty compiler caches,
sustained loading, different hardware/drivers, optional full-precision A14B and
actual bundled-image inference require separate evidence. The full bundled image
was not built during this managed-engine test. Operator engine preparation and
the existing policy-update procedure remain explicit; existing deployments are
not changed automatically. Public HTTPS, production economics and paid operation
are outside this window.
