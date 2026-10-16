# RTX 5090 workload and recovery validation — 2026-10-15

This extends the [initial generation report](gpu-validation-2026-10-15.md) with catalog-resolution workloads, longer clips, memory measurements and deliberate interruptions of the owned deployment. The host, pinned engine images and pinned weights are the same. The shared Docker daemon and unrelated workloads are not restarted by these tests.

## Workload method

For each default model, `src/video_runners/tools/validate_gpu.py --catalog-defaults --mode both --repeat 2 --clips 2` submits two single-shot clips and two persistent sessions containing two clips each. Each decoded MP4 is checked for its requested dimensions, frame count and changing frames. A separate two-mode run uses 121 frames at the same 832×480 resolution.

Measurements cover loaded-engine requests through the Livepeer node, including polling and delivery. NVIDIA memory is sampled approximately every 0.5 seconds. cgroup v2 measurements record current memory, its lifetime peak, anonymous memory, file cache and OOM kills. GPU maxima are sampled observations, not guaranteed instantaneous peaks. The cgroup lifetime peak includes startup and file cache; it must not be presented as process heap usage. Independently sampled anonymous/file-cache maxima need not occur together.

The trials were short repeated sequences, not a long-duration soak test. Clips, previews, metadata and raw samples were generated under the operator's ignored artifacts directory and subsequently removed during the requested cleanup. This report retains the measured results; it does not describe a running deployment.

## Workload results

| Profile                                     | Resolution / frames | Clips verified | Request timings                                                            | Maximum sampled GPU memory |
| ------------------------------------------- | ------------------- | -------------- | -------------------------------------------------------------------------- | -------------------------- |
| SGLang FastWan 1.3B                         | 832×480 / 61        | 6              | single-shot 6.20–6.23 s; two-clip sessions 11.21–12.21 s                   | 14,805 MiB                 |
| SGLang FastWan 1.3B                         | 832×480 / 121       | 2              | single-shot 13.21 s; persistent 13.21 s                                    | 10,473 MiB                 |
| vLLM-Omni Wan 5B, previous resident profile | 832×480 / 49        | 6              | single-shot 21.21–21.45 s; two-clip sessions about 44 s                    | 32,094 MiB                 |
| vLLM-Omni Wan 5B, CPU offload + VAE tiling  | 832×480 / 49        | 6              | first single-shot 32.40 s, warm 25.32 s; two-clip sessions 50.27–50.28 s   | 13,772 MiB                 |
| vLLM-Omni Wan 5B, CPU offload + VAE tiling  | 832×480 / 121       | 2              | single-shot 73.98 s; persistent 71.49 s                                    | 14,990 MiB                 |
| LightX2V Wan 1.3B                           | 832×480 / 81        | 6              | first single-shot 70.32 s, warm 54.29 s; two-clip sessions 109.38–109.45 s | 20,352 MiB                 |
| LightX2V Wan 1.3B                           | 832×480 / 121       | 2              | single-shot 95.34 s; persistent 95.38 s                                    | 20,412 MiB                 |

The resident vLLM profile left only 513 MiB below the card's reported 32,607 MiB total. The Wan 5B public and trusted catalogs now enable `--enable-cpu-offload` and `--vae-use-tiling`. This trades some latency and host-memory/cache traffic for substantially more VRAM headroom. Existing deployments must deactivate the old engine before loading the changed trusted catalog.

No cgroup OOM kills were observed in these completed workloads. SGLang's lifetime cgroup peak reached its 48 GiB allowance; the offloaded vLLM engine reached its 32 GiB allowance, including reclaimable file cache. These measurements do not imply that either engine needs that much anonymous RAM.

## Recovery behavior found and fixed

The initial idle-engine exit test withdrew the runner from discovery but did not relaunch the owned engine. The host-side baseline record showed no registrations 12 seconds after exit; explicit admin activation restored it.

The runner now attempts one owned reset after three consecutive failed health checks, once its GPU job lock is idle. It withdraws registration immediately. Failed reset retains `recovery_required` and remains unavailable instead of repeatedly reloading. External lifecycle mode continues to leave restart ownership with its operator.

Regression coverage adds three behaviors: idle recovery, waiting for active GPU work, and failing closed after a failed reset. The idle recovery test failed before the fix; removing the GPU-idle guard also made the active-work test fail. The full unit suite passed 94 tests, and the combined CPU Docker integration passed delivery, switching, restart and proxy checks.

## Recovery procedure

`uv run src/video_runners/tools/validate_recovery.py --engine ENGINE` operates against the combined managed deployment on its free offchain test node. It verifies the daemon-issued engine ID against durable controller state and the trusted catalog before interruption. It refuses active user work at entry and does not support paid fault injection. Individual cases cover:

- Disconnecting a single-shot client after the engine reports a job status.
- Releasing a persistent session with an active job, including verifying HTTP 503 for concurrent generation.
- Killing an idle owned engine.
- Killing an owned engine during an active persistent job.
- Crashing the idle runner process and restarting its controller.

After each fault it observes at most one running engine in the namespace, waits for idle readiness and discovery, and generates a fresh clip. It never automatically retries a failed generation. `--cases` narrows the checks; `--skip-generation` is a diagnostic option and does not establish rendering recovery.

The runner process crash uses a host PID file descriptor to pin the verified container process before sending SIGKILL. The first harness attempt used the Docker kill API, which counts as a manual stop and intentionally suppresses restart policy; that attempt was a harness baseline and is not counted as a crash-recovery pass. Its raw log was removed with other test artifacts. See [Docker restart-policy details](https://docs.docker.com/engine/containers/start-containers-automatically/#restart-policy-details). Session cleanup also tolerates HTTP 404 for an old registration that recovery already removed.

| Fault                          | SGLang recovery | vLLM-Omni recovery | LightX2V recovery |
| ------------------------------ | --------------- | ------------------ | ----------------- |
| Client disconnect during work  | 7.16 s          | 81.30 s            | 20.25 s           |
| Stop active persistent session | 68.24 s         | 67.04 s            | 11.14 s           |
| Kill idle owned engine         | 61.15 s         | —                  | —                 |
| Kill engine during work        | 55.00 s         | 36.61 s            | 45.58 s           |
| Crash idle runner process      | 62.24 s         | —                  | —                 |
| Restart controller             | 120.28 s        | —                  | —                 |

All recorded table cases also produced a verified fresh video afterward. The three session-stop cases rejected concurrent generation with HTTP 503. SGLang finished its short disconnected job before the connection loss was noticed and retained that engine; vLLM and LightX2V replaced theirs before readmission. The table records one observed recovery per case, not a latency guarantee. A dash means the case was not run for that engine.

The 12 selected hardware recovery cases passed with verified generation afterward. A runner process crash restarted through Docker's `unless-stopped` policy; the controller restart also reloaded the engine before registration returned. These exercised recovery of this shared deployment, not every possible failure point.

The shared Docker daemon and unrelated host services were not interrupted. Daemon/host outages, runner crashes during an active job, every intermediate model-load failure point, long-duration soak, MiniMax-H3, Wan A14B and the optional non-distilled SGLang entry remain unvalidated on hardware. The [historical legacy paid trial](paid-validation-2026-10-15.md) is recorded separately; the [replacement-node report](node-paid-validation-2026-10-16.md) adds paid single-shot SSE evidence. Paid persistent delivery, winning-ticket redemption and final on-chain settlement remain pending.
