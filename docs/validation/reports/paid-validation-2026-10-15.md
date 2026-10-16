# Historical legacy paid compatibility trial — 2026-10-15

All three default GPU models generated verified videos through **go-livepeer v0.9.3 on Arbitrum mainnet**, using a gateway/payment signer on a separate client machine. Both single-shot SSE and persistent trickle delivery passed. This extends the [GPU workload and recovery validation](operations-validation-2026-10-15.md); it does not establish winning-ticket redemption or final on-chain settlement.

This records a completed compatibility experiment, not the supported deployment architecture. The replacement uses `livepeer/node` for orchestrator and signer, with the Python SDK as the application client. The legacy deployment files and runtime test resources have been removed. Replacement-node coverage is recorded separately in the subsequent report below.

Subsequent evidence: the [October 16 node trial](node-paid-validation-2026-10-16.md) verifies paid single-shot SSE for all three defaults without legacy daemons or tunnels. The measurements below remain the historical October 15 trial.

## Deployment

- GPU host: the same RTX 5090, driver, pinned engines, weights and external cache/state volumes as the earlier report.
- Orchestrator: a separate temporary Compose project reusing an existing external wallet/data volume. Operator-specific resource names are omitted. Image: `livepeer/go-livepeer@sha256:dd5c2d07aa2b279475b24ee17dd52e3a8ac79d7984265ad0233d3f0efbb06bb3`.
- Dynamic registration enabled with `-useLiveRunners`; client and runner callback URLs configured separately. The CPU runner joins an existing private Docker network. GPU engine, controller and Docker API networks do not join ingress.
- Orchestrator host port and runner admin bind to loopback. A reconnecting SSH user service forwards them to the client machine. No public HTTPS endpoint or on-chain service-URI update was performed.
- Local gateway and signer: go-livepeer v0.9.3 CPU release in a roughly 244 MB image. Release SHA-256: `09753d57d387d7301d555a2064e3bc5bcb3b3c28373ca123eae761c1f8f8689e`.
- The signer alone mounts the existing encrypted gateway keystore directory read-only. Keys remain on the client machine. Gateway/signer state uses external Docker volumes. Private env files have mode `0600`.
- A separate operator-owned public catalog sets **$1/hour** test pricing. The local signer has a **$2/hour** rate ceiling and an explicit single-orchestrator destination. Repository defaults remain zero-priced for offchain tests. No deposit or token-approval transaction was submitted by the deployment tooling.

Use the [node deployment instructions](../../guides/node-deployment.md) for the current code. This report's legacy image and measurements describe only that earlier experiment.

## Generation results

The Python SDK obtained discovery from the legacy remote signer, used it for payment signing, and sent application requests through the tunneled orchestrator. A separate traditional gateway process was started unnecessarily; application requests did not use it. It was removed during cleanup.

`validate_all.py --catalog-defaults --mode both --signer ...` (now at `src/video_runners/tools/validate_all.py`) switched SGLang → LightX2V → vLLM-Omni and restored SGLang. The validator decoded every frame, checked exact requested dimensions/frame counts, required changing frames and verified the delivered file hash. Each mode requested one clip with seed 42 and the fox prompt from the initial report.

| Engine / model      | Video                                | Steps | Single-shot request | Persistent request | MP4 bytes |
| ------------------- | ------------------------------------ | ----- | ------------------- | ------------------ | --------- |
| SGLang FastWan 1.3B | 832×480, 61 frames, 16 fps, 3.8125 s | 3     | 6.41 s              | 6.53 s             | 404,855   |
| LightX2V Wan 1.3B   | 832×480, 81 frames, 16 fps, 5.0625 s | 30    | 69.51 s             | 54.62 s            | 283,382   |
| vLLM-Omni Wan 5B    | 832×480, 49 frames, 24 fps, 2.0417 s | 30    | 35.81 s             | 29.30 s            | 622,150   |

Times include payment setup, inference and delivery with already loaded engines. First requests can include compilation. These different models/steps are functional trials, not comparative engine benchmarks. GPU/cgroup telemetry was measured separately in the workload report; the client-side paid run did not sample GPU memory remotely.

Within each engine process the two delivery modes produced matching files:

| Engine    | SHA-256                                                            |
| --------- | ------------------------------------------------------------------ |
| SGLang    | `a9a7b0b263042579627c4dca231f56e82527175ae1093fb8c8f6dafbed39f3f8` |
| LightX2V  | `7e87e3d74b765ea851f55efc97329f701a04836b946e146a2e1e56cd5998bb21` |
| vLLM-Omni | `fda2870b5f6a150bb998344d7929c253c8bf09c468d40db4aa21ca598ccfd44a` |

Selecting the already active SGLang took 0.01 s. Switching to LightX2V took 24.41 s; switching to vLLM-Omni took 41.83 s. These are single observed load times. Remote signer discovery can lag a model switch; the validator waits for the new apps before submitting work, retrying discovery rather than generation.

## Payment and final-state evidence

Before rendering, a request with a valid payer address and no payment received **HTTP 402** with payment parameters. Runner admin status confirmed an idle GPU and no reserved sessions afterward.

The signer recorded **69 signed payment batches across six payment sessions**, including renewals during the longer LightX2V/vLLM requests. All six resulting videos passed validation. A signed-batch count is not a settlement receipt or a measure of funds finally spent; unused credit, probabilistic ticket outcomes and redemption are separate concerns.

Immediately after the run, the runner was idle with no open sessions or recovery flag, and signer discovery listed only the two SGLang apps. At the operator's subsequent request, all task-owned test services, tunnel installation, deployment copies, temporary state volumes and private test env files were removed. The existing wallet, model/cache volumes and host key files were preserved.

Generated MP4s, previews, metadata, raw logs and receipts were also removed as requested. The timings and hashes recorded above remain in this historical report; there are no retained video artifacts or live endpoints to inspect from this run.

## Remaining release checks

Public HTTPS routing, production prices, long-duration operation, paid fault injection, winning-ticket redemption/final settlement, larger optional models and multi-GPU behavior remain separate checks. The fault-injection helper targets the free offchain test node and rejects priced discovery. Shared-daemon controller trust and per-mode admission limitations still apply; see [SECURITY.md](../../../SECURITY.md) and the README.
