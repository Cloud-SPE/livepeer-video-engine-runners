# RTX 5090 validation — 2026-10-15

All three default engines generated real MP4 videos through the Livepeer orchestrator and CPU runner in managed mode, using both single-shot SSE and persistent trickle delivery. These were GPU inference runs, not CPU substitutes.

This report records the initial small-clip runs. The later [workload and recovery report](operations-validation-2026-10-15.md) adds 832×480 workloads, longer clips, measured memory and fault injection. It also changes the Wan 5B profile to CPU offload and VAE tiling; the vLLM timings below used the earlier resident profile.

The test environment used Linux, NVIDIA driver 580.178.04, Docker 29.8.1 and an RTX 5090 reporting 32,607 MiB VRAM. Host identifiers and private resource names are omitted. A CUDA 13 PyTorch tensor operation passed before inference testing. The orchestrator used the repository's pinned livepeer-node source commit; engine images, LightX2V source and weight revisions are recorded in `configs/engine-images.json` and `configs/model-assets.json`.

## Generation results

Every request used seed 42, 512×288, 49 frames and this prompt:

> A small red fox walks slowly across a snowy forest clearing. Soft golden sunlight, realistic fur, gentle camera movement, cinematic natural colors.

| Engine    | Model                | Steps | Output                                     | Single-shot request | Warm persistent request |
| --------- | -------------------- | ----- | ------------------------------------------ | ------------------- | ----------------------- |
| SGLang    | FastWan 2.1 T2V 1.3B | 3     | 49 frames, 16 fps, 3.0625 s; 81,707 bytes  | 3.24 s              | 2.18 s                  |
| vLLM-Omni | Wan 2.2 TI2V 5B      | 30    | 49 frames, 24 fps, 2.0417 s; 585,878 bytes | 8.20 s              | 8.23 s                  |
| LightX2V  | Wan 2.1 T2V 1.3B     | 30    | 49 frames, 16 fps, 3.0625 s; 65,527 bytes  | 26.25 s             | 9.18 s                  |

Timings include discovery, job submission, inference polling and delivery, with loaded engines. The LightX2V first request included kernel compilation. SGLang performs startup warmup before registering. Different models, step counts and initialization behavior make these functional checks unsuitable as comparative engine benchmarks.

The validator decoded every frame with PyAV, required changing frames, saved a PNG preview and recorded each MP4's SHA-256. All six videos had 49 unique decoded frames. For each engine, both delivery modes produced matching MP4 hashes for the fixed seed:

| Engine    | SHA-256                                                            |
| --------- | ------------------------------------------------------------------ |
| SGLang    | `5aa21c18ab6339d7ed31de1f3408660dba5f93bb782caebe108ceecee0560115` |
| vLLM-Omni | `8092e66fba1fc37f46e4cd011be51f3d32b61f67bab10341a7ac126292328205` |
| LightX2V  | `2894bcb85165000e631a6db8808b17a71ce2ee1d118b2f53e978efd3da5d9010` |

Generated videos, previews, JSON and logs were excluded from Git and subsequently deleted during the requested cleanup. The report retains the measurements and hashes. Generate new artifacts using [`src/video_runners/tools/validate_gpu.py`](../../../src/video_runners/tools/validate_gpu.py) and the [deployment guide](../../guides/container-deployment.md). Visual quality is model-dependent; these were short, low-resolution functionality checks.

The final combined deployment also passed six more generations while switching SGLang → LightX2V → vLLM-Omni, then restored SGLang. Loading LightX2V after SGLang took 27.60 seconds; loading vLLM-Omni after LightX2V took 43.63 seconds. Selecting the already active SGLang model was a no-op. These are single observed switch times, not guaranteed deadlines. The repeatable [`src/video_runners/tools/validate_all.py`](../../../src/video_runners/tools/validate_all.py) performs this check. Fixed seeds matched between delivery modes within each engine process; byte-for-byte reproducibility across engine restarts is not guaranteed.

## Problems found and fixed

- SGLang's initial 16 GiB host-memory limit caused a kernel-confirmed cgroup OOM while loading its approximately 21 GiB text encoder. Its trusted catalog now allows 48 GiB host memory. The card's VRAM limit is separate.
- Plain text fields in `aiohttp.FormData` defaulted to URL encoding. SGLang did not parse those fields, rejecting the prompt as missing. Fields are now explicitly multipart, covered by an HTTP regression check.
- Managed startup with an explicit model could race a previous engine reset. Startup now waits for controller recovery, and the wait participates in shutdown handling.
- vLLM-Omni generated a larger MP4 that exceeded the SDK's SSE line limit after base64 expansion. Binary chunks are now 256 KiB. A 1 MiB payload round-trip through the pinned SDK covers the failure.

## Storage and operational checks

Weights were staged into external named Docker volumes. Downloads in progress were preserved when the validation setup moved to those volumes. Repeating the pinned preparation tool for all three default models reused the files and produced ready receipts without transferring the model weights again. SGLang and vLLM-Omni were recreated and loaded offline from the saved cache. External controller state survived Compose teardown with `down -v`.

The deployment supports persistent Torch, TorchInductor, Triton, CUDA and vLLM caches in an external engine-cache volume. The model/cache volumes and existing wallet were preserved during cleanup. Temporary test controller/lease state volumes and deployed copies were removed. Generated videos were separate artifacts, not model-cache contents.

A second controller using a separate state directory was refused the active GPU by the shared lease on the actual host. This does not exclude unrelated GPU applications.

The CPU integration matrix covers all five catalogs (`stub`, `sglang`, `lightx2v`, `vllm-omni`, `all`), both delivery modes, model/API switching, runner/controller restart, exact proxy denials and network isolation. Ownership, rollback, interrupted operations, shared GPU leases and durable-state errors also have automated coverage.

## Limits of this validation

These results validate the three listed model/image/configuration combinations at the stated small resolution. They do not establish peak VRAM, sustained throughput, concurrent multi-GPU behavior, larger default resolutions, MiniMax-H3, Wan A14B, the optional non-distilled SGLang model, GPU cancellation during arbitrary kernels, daemon outages, or paid/onchain settlement. The shared-daemon controller trust boundary described in [SECURITY.md](../../../SECURITY.md) remains.
