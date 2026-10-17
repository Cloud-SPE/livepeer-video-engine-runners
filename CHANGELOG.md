# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Registry-independent container release planning/publication and digest-only
  deployment manifests for distinct runner/controller/node/model-tools/LightX2V
  images; manual CI workflow and image overrides in existing Compose entry points.
- Normal CPU publication reuses verified unchanged engine/node digests; changed
  engine inputs require an explicit engine release. Routine CI uses hosted workers
  without GPU image pulls or a self-hosted build-worker service.
- Private bearer-authenticated Prometheus metrics for generation/delivery outcomes,
  latency, admission refusals, switching, state and owned-engine recovery.
- Configurable 120-second graceful model-switch drain and explicit boolean force
  switching with confirmed owned-engine termination before replacement. Failed
  stop/cleanup keeps admission closed; existing ownership/delivery modes remain.

- Opt-in video-quality harness with versioned prompts/suites, reproducible plans,
  bounded SDK generation, checksum-checked resume, isolated pinned VBench
  evaluation and blind video review with exportable preferences/usability.
- Optional LightWan 2.2 A14B NVFP4 profile with pinned selective assets and
  matching launch policy; real RTX 5090 SDK pilots at 480p and 720p. Existing
  models, defaults and ownership modes remain unchanged.
- Optional OpenAI-video sampling controls for guidance scales and flow shift,
  with client FPS/negative-prompt options and backend capability checks.

### Fixed

- Cancel pending admin switches during shutdown and refuse new switches once
  shutdown begins, so they cannot start a replacement engine afterward.
- Release the GPU reservation when force cancels an admitted persistent task before
  it begins, and keep initial-loading generation refusals from raising an assertion.

- Permit authenticated deactivation after a controller operation fails, while
  retaining durable ownership checks and rejecting new activation until recovery.

- Normalize mount ordering in CPU cleanup fingerprints while retaining checks for changed mount sources, permissions and propagation.
- Print a bounded redacted CPU step log on failure even when resource inspection fails, preserving the original startup diagnostic in CI.
- Provision a pinned API-compatible Docker daemon for managed CI, use its matching Buildx context/proxy socket, and update Dependabot to the canonical Dockerfile directory.

## [0.2.0] - 2026-10-16

### Changed

- Two real Compose entry points: `compose.prod.yml` connects the managed provider to an existing node; `compose.dev.yml` brings up the complete free CPU development stack. Optional asset/signer/ingress and bundled/external recipes remain explicit supporting files. Existing runtime modes, delivery APIs and lifecycle semantics are retained.
- Generalize deployment examples and validation summaries, removing operator host/account/resource identifiers. Document image names and correct stale command, discovery and payment-status descriptions.
- Remove all compatibility symlinks, root Python forwarding modules and the mode-selection deployment wrapper. Use installed `video-*` commands and canonical tool/test/Dockerfile paths. See the [migration guide](docs/guides/repository-layout.md) before updating existing commands; preserve private env settings and external volumes.

### Added

- Direct-LAN paid single-shot verification of all three default RTX 5090 engines using the Python SDK, local `livepeer/node` signer and remote node orchestrator. Record payment challenges/renewals, decoded outputs and owned cleanup; document mapped signer ownership, exact password bytes and literal runner IPs. No SSH tunnel or legacy daemon is required.

- Isolated bundled/managed CPU harnesses with per-worktree/run images and resources, verified cleanup manifests and retained versioned receipts. Hardware validators use unique outputs and a cooperative host lease; lifecycle logs correlate runner/controller operations without changing protocol or state schemas. CI retains selected CPU evidence.
- Independent combined-catalog generation, pinned image/asset/launch consistency checks and a source-derived CLI/data reference. Fast checks reject generated-file drift; checkout-based operator tools share literal env parsing and checked output capture.
- Installable `src/video_runners/` package with separate backend, lifecycle, runner and controller modules; packaged runtime commands. Deployment sources now live in `deploy/`, tests are grouped by resource needs, and guides/design/validation have dedicated directories. Static boundary checks cover package-relative imports and initializers; CI checks wheel installation outside the checkout.
- Repository navigation, architecture and engineering principles, a phased refactor plan, technical-debt tracking and a validation matrix. `scripts/check.sh` runs local link/anchor/index and static dependency checks, Black, Ruff and CPU tests; CI uses the same command.
- Canonical livepeer/node orchestrator and optional client-side signer configuration, an ingress overlay with a stable IP for node grants, operator-owned public pricing catalogs, and an SSH tunnel template. The Python SDK uses the signer directly; no traditional gateway daemon is required. GPU validators accept a signer URL.
- Hardware reports for 832×480 and 121-frame workloads, 12 selected recovery cases, and a historical six-clip paid mainnet trial using the legacy go-livepeer signer. Replacement-node paid persistent delivery, final settlement and public deployment remain separate gates.
- Catalog-resolution workload validation, repeated persistent clips, host GPU/cgroup memory telemetry, and owned-container recovery checks with fresh generation after each fault.
- External Docker volumes for model downloads, controller state and a shared per-GPU lease; private deployment initialization, pinned resumable weight preparation, and an existing-orchestrator Compose overlay.
- Managed and external deployment support for LightX2V and vLLM-Omni, an engine-only LightX2V build on a pinned RTX 5090 base, image preparation and deployment helpers, and a combined catalog for switching across all three engines on one GPU.
- Catalog contract tests and CPU Docker fixture coverage for each real engine catalog and cross-engine switching, plus [RTX 5090 validation](docs/validation/reports/gpu-validation-2026-10-15.md) of the three default GPU models in both delivery modes.
- Version 0.2.0 lifecycle configuration: `--lifecycle=bundled|external|managed`, external engine URL, and authenticated controller connection. Bundled remains the default; external mode rejects runtime model switching.
- Separate CPU runner/controller images and external/managed Compose deployments. CUDA, engine packages, GPU access, and weights stay with the engine container.
- Managed switching through a pinned Tecnativa Docker socket proxy with exact API routes, a trusted digest-pinned model catalog, reserved GPU UUID, durable container ownership and operation IDs, rollback, and restart recovery. The runner never receives Docker API access.
- Engine health monitoring withdraws registration and refuses work while the backend is unavailable, then reconnects after recovery.
- [Deployment instructions](docs/guides/container-deployment.md), a [phased rollout](docs/design/engine-container-rollout.md), and managed CPU end-to-end checks for delivery modes, switching, recovery, and proxy isolation.
- Runner for LightX2V, SGLang Diffusion and vLLM-Omni on livepeer-node, one process per GPU, registering two apps that share one GPU lock:
  - single-shot `video:generations/<model>`: `POST /generate` streams progress and the MP4 over Server-Sent Events;
  - persistent `video:sessions/<model>`: `POST /session/start` and `/session/jobs` render clips into trickle `video` and `events` channels.
- Per-engine model catalogs, and runtime model switching through an authenticated admin API with rollback on failure.
- Immediate refusal of busy requests (503 / 409), cancellation requests on disconnect, owned-engine recovery for unknown outcomes, idle session release, and clean deregistration on SIGTERM.
- CPU stub engine speaking both engine APIs, reference client, unit tests and an end-to-end script.
- Docker images per engine, and compose files that build the orchestrator from a pinned livepeer-node commit.
- CI: lint, unit tests, compose validation and an end-to-end run with the stub engine.

### Fixed

- Deployment documentation now distinguishes the canonical node orchestrator/signer from historical legacy trials, reflects named-volume storage and cancellation/billing limits, and records removal of runtime test artifacts. Legacy gateway/orchestrator deployment files were removed.
- Idle owned engines now attempt one reset after persistent health loss, wait for active GPU work, and fail closed if reset fails. The RTX 5090 Wan 5B profile enables CPU offload and VAE tiling to leave VRAM headroom at 480p.
- Large single-shot videos now use SSE chunks small enough for the pinned SDK's line reader after base64 encoding.
- Video API fields are explicitly multipart for SGLang compatibility; managed startup waits for controller recovery even with an explicit model selection. SGLang's host RAM allowance is 48 GiB after a real 16 GiB cgroup OOM during text encoder loading.
- External engine launches now use the same model catalog and `MODEL` as the runner, preserving model-specific launch flags.
- LightX2V requests carry their configured task, including MiniMax-H3 `t2av`; unsupported H3 negative prompts are rejected before admission.
- Failed cancellation responses are reported. Interrupted or uncertain jobs withdraw availability and reset owned engines before readmission; external engines require operator recovery.
- Trickle segments are sent as complete requests, and quiet session channels get keepalive segments, so sessions survive idle gaps and long renders.
- A persistent client no longer hangs when a job is refused as busy.

[Unreleased]: https://github.com/Cloud-SPE/livepeer-video-engine-runners/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Cloud-SPE/livepeer-video-engine-runners/tree/v0.2.0
