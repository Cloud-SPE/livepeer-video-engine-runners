# Video-quality harness and larger-model pilot — 2026-10-16

This records an opt-in SDK pilot on one RTX 5090 (32,607 MiB, driver 580.178.04)
with about 91 GiB of host RAM. The client used direct private LAN discovery through
a free offchain `livepeer/node` orchestrator, runner and managed controller. No
SSH tunnel, legacy daemon, payment keys or funded signer was needed. This adds
no paid-operation evidence. Existing profiles and defaults are preserved.

## Method and generation evidence

All six jobs used the pilot's fox-walking prompt and seed 42. Each MP4 was
received through single-shot SSE, checksum-verified, decoded, and checked against
requested dimensions, frames and FPS. Timings include SDK delivery and local
inspection after the engine was ready; startup is excluded. Each row is one
observation, not a throughput or reliability estimate. Different durations,
checkpoints and recipes make these native-profile comparisons, not controlled
single-variable quality experiments.

| Profile                                            | Dimensions | Frames / FPS | Steps     | End-to-end seconds |
| -------------------------------------------------- | ---------- | ------------ | --------- | ------------------ |
| SGLang FastWan 1.3B current                        | 832×480    | 61 / 16      | 3         | 6.75               |
| SGLang FastWan native-size candidate               | 832×448    | 61 / 16      | 3         | 5.74               |
| LightX2V Wan 1.3B current                          | 832×480    | 81 / 16      | 30        | 69.75              |
| vLLM-Omni Wan 5B current, CPU offload / VAE tiling | 832×480    | 49 / 24      | 30        | 31.80              |
| LightWan 2.2 A14B NVFP4                            | 832×480    | 81 / 16      | 4 trained | 27.80              |
| LightWan 2.2 A14B NVFP4                            | 1280×720   | 81 / 16      | 4 trained | 40.44              |

The 480p LightWan trial used a candidate image adding only the new configuration
on the previously prepared pinned LightX2V image. Normal asset preparation then
passed offline, and `prepare_engines.py lightx2v` built the reusable image used
for the successful 720p run. Its immutable local image ID was
`sha256:7d3fe67ce806e6736d84566c788b9073b2452d64293c10b5c88826c0e3d6f013`.
A local ID is not a portable registry reference.

The 720p run used the canonical 32 GiB host-memory limit. Sampling every 0.5 s
observed 31,684 MiB GPU memory; the engine's lifetime cgroup peak was
18,020,401,152 bytes (16.78 GiB), including startup and file cache. No cgroup OOM
kills were recorded. These are sampled GPU and cgroup measurements, not exact
instantaneous VRAM or heap requirements. Only 923 MiB separated sampled usage
from reported GPU capacity; longer/larger workloads need new validation.

Output SHA-256 values, in table order:

```text
90126d0c75128d83a1759bd54feb30eb996d0b80fbf69cbad907dff0f37d7562
c81e0a36a79d9b63251979f2e88f3eda093fde2f5c79d3b4f3a12283d91531d9
de9951269bc467c8ace26f0fa3f4ae1e3ccd8baace2239ec99195ca57c3ae7a5
3284d90c823d83326ec3c3ea01faede6a91e828d97d6e11d6f39bb7d42077621
2e781ec84841c19aebac22e3b172c3d2fb66a3a41a53740a79fb1ee2eb227526
7af8e412a12d93aac6f1ce87759927aa9fbc09dc8baaf8aa84692e750cf6b3d0
```

## Reproduction inputs

The pilot ran uncommitted quality-harness changes on base revision
`6501bda7b4030839c4c94765d353a831d8eb1986`. Private per-run plans retain input
hashes, resolved requests/catalog entries and configured pin contents. This
report does not pretend that the base revision alone reproduces those changes.
Use the resulting feature revision and the [quality guide](../../guides/video-quality.md)
for new runs; changing provenance produces a new plan identity.

SGLang and vLLM use the unchanged immutable references in the
[image manifest](../../../configs/engine-images.json). LightX2V uses base
`sha256:fdfebaded08f8d68f1ea86e19d3f8804206479a82076ef12dba414f58a452761`
and source `8e86555809efd20138d3a4e1f937ee306cdf0ee0`. The new profile uses:

- Wan base `Wan-AI/Wan2.2-T2V-A14B` at
  `c8c270b13ee05bfa474194ac9fb07a5868a97cea`, selectively staged configuration,
  tokenizer, text encoder and VAE.
- `lightx2v/LightWan2.2-A14B` at
  `f4b91eba1fd7dc2eb038191e2bca7ed33423032d`, two NVFP4 sparse experts.
- [Checked-in engine configuration](../../../configs/lightx2v/wan22_nvfp4.json):
  four distilled steps, sparse attention, CPU text encoder and GPU experts.
  Negative prompts are unsupported by this CFG-free API. The initial candidate
  request was rejected before generation for supplying an empty negative prompt;
  the new profile's capability flag fixes that mismatch.

Original/current model asset pins remain in the
[asset manifest](../../../configs/model-assets.json). Request values are
requested/configured settings; decoded properties and engine logs provide
separate observations. Identical seeds do not establish identical noise across
engines. See the [upstream LightWan model card](https://huggingface.co/lightx2v/LightWan2.2-A14B)
for the distilled NVFP4 model, which differs from full-precision Wan A14B.

## Failed startup experiments and recovery

Two private full-precision vLLM A14B layerwise-offload startup attempts, including
serial shard loading, reached an 80 GiB host-memory limit without becoming ready.
No generation was submitted. Their owned engines were stopped and host memory
recovered; no daemon restart, GPU reset, global cache flush or unrelated-service
interruption was used. These recipes are not added to the public catalogs.
The original optional full-precision A14B entry remains available with its prior
hardware requirements; this pilot does not validate it on a 5090.

The current vLLM 5B generated a clip but had intermittent startup-warmup failures
in the pinned engine's asynchronous output path (a hard-coded 30 s wait). An
explicit trial of `--step-execution` failed earlier: this version's `WanPipeline`
does not implement that execution contract. That failed option is not shipped,
and no vendor source was patched. Startup reliability needs further work.

Testing also exposed a controller error state that rejected authenticated stop
along with new activations. The controller now allows deactivation from error
when no operation is active, preserving all durable ownership/configuration
checks. CPU HTTP regressions cover authentication, refusal of foreign resources,
new activation rejection and clearing the error after successful deactivation.
The updated controller deactivated verified owned hardware resources during the
trial without deleting or editing its journal.

## Quality interpretation and remaining review

Six valid moving videos establish model fit and end-to-end delivery for these
specific workloads. They do not establish better perceptual quality. A blind
six-video gallery contains fifteen matched prompt/seed pairs, with exportable
preferences, usability and reasons. Clips and private provenance are retained
locally for operator review, outside version control.

All six clips completed all six automated dimensions; results are below. Human ratings, eight-prompt screening and held-out
confirmation remain required before claiming a winning preset. Higher-step vLLM
and other suite candidates are planned experiments, not validated profiles.

## Automated custom-input measurements

The isolated evaluator used VBench `fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490`,
`custom_input` mode and imaging preprocessing `longer`. Original clip hashes,
plan identities and returned evaluator inputs matched during score import.
No dimensions were missing. The final optional image ID was
`sha256:2ba224881b4e4cb4cc0d00002da3a9ef4124bd4d80fe992da6bad736c58a0060`.

| Native profile           | Subject consistency | Background consistency | Motion smoothness | Dynamic degree | Aesthetics | Imaging |
| ------------------------ | ------------------- | ---------------------- | ----------------- | -------------- | ---------- | ------- |
| FastWan current          | 0.9891              | 0.9419                 | 0.9905            | 1.0000         | 0.6305     | 0.6442  |
| FastWan native size      | 0.9910              | 0.9890                 | 0.9876            | 1.0000         | 0.6210     | 0.6358  |
| LightX2V Wan 1.3B        | 0.9956              | 0.9931                 | 0.9970            | 0.0000         | 0.6230     | 0.7046  |
| vLLM Wan 5B              | 0.9619              | 0.9710                 | 0.9969            | 0.0000         | 0.5357     | 0.4711  |
| LightWan A14B NVFP4 480p | 0.9812              | 0.9808                 | 0.9923            | 0.0000         | 0.6808     | 0.6419  |
| LightWan A14B NVFP4 720p | 0.9723              | 0.9778                 | 0.9898            | 0.0000         | 0.6899     | 0.6455  |

These are one-clip scores on a custom prompt, not VBench leaderboard results or
confidence estimates. Dynamic degree is a binary per-clip threshold here: zero
means the detected motion did not meet that criterion, not proof of identical
frames. Smoothness/consistency can favor restrained movement. The requested walk
and visual artifacts need human review. Higher aesthetics for LightWan and higher
imaging for the smaller LightX2V profile are mixed signals; no overall score or
winner is inferred.

The evaluator recorded 11 cached weight hashes and 12 Python/YAML source hashes.
Some upstream components fetch moving sources, so retaining and matching that
cache matters as well as the VBench source pin. Resolved package metadata uses
Python import-path precedence, avoiding duplicate base/virtualenv distributions:
`torch 2.11.0+cu130`, `torchvision 0.26.0+cu130`, `timm 1.0.12`, `pyiqa 0.1.16`, `openai-clip 1.0.1`, `decord 0.6.0`.
Private result wrappers retain the full manifests. Their sorted-JSON SHA-256
fingerprints are:

- Cached weights: `886d907f073ed1cbecb99fc84427ea8bd2fd5b1bf8e3e61c02ec921342d048cd`.
- Cached Python/YAML sources: `1c6ec4a6c02c52aae6e097659c2151732f6669b1f70080c1fbb9314dc50e0404`.

Generation services were stopped and their GPU lease released before evaluation.
The evaluator acquired that same lease, exposed one assigned GPU, and used an
external persistent quality-cache volume. It had no signer keys or Docker socket.

## Repository verification and cleanup

The final fast checks passed 192 CPU tests, Black/Ruff, repository links/import
boundaries and generated configuration agreement. All 33 Compose configurations
resolved. Isolated combined-catalog managed and bundled CPU integrations passed
with 22 decoded fixture clips, including delivery and managed recovery/proxy
checks; their owned resources were removed. Wheel build and fresh installation
outside the checkout passed the four runtime entry points and both quality-tool
help commands. These CPU checks do not broaden the GPU pilot's workload scope.

The optional evaluator image was built and all six clips measured successfully.
No browser surface was available for interactive gallery playback/export QA;
manual operator review remains pending. Routine checks and raw-score imports
cover the report and summary contracts without substituting for that review.

Cleanup removed all 28 verified owned test containers, their four networks,
private image aliases, the newly created empty/disabled test controller journal
and private deployment staging. The reusable prepared LightX2V and optional
evaluator images remain. External HF/model/engine/quality caches, shared GPU
lease data, existing wallet data and host keys remain. Unrelated shared-host
services were not changed. The GPU returned to 2 MiB reported usage. Original
videos, score wrappers and the blind gallery remain privately available for
review; no deployment is left running by this pilot.
