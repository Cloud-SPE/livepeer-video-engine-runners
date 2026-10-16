# Validation matrix

This is an evidence index, not a claim that a deployment is running. Dated GPU
reports describe the October 15–16, 2026 runs. Earlier deployment-trial videos and
raw receipts were removed at the operator's request; quality-pilot clips remain
private for review. Measurements and hashes remain in the reports. Public
summaries omit operator hostnames, actual addresses, account identities, private
resource names and worktree-derived run IDs. GPU/image/model versions and measured
results describe the tested configuration. Wallet/model/cache volumes and host
keys were preserved.

## Automated checks

| Area                                                          | Evidence                                                                                 | Limit                                                                        |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Catalogs, API adapters, delivery, lifecycle and controller    | [CPU tests](../../tests), run by [fast checks](../reference/checks.md#fast-local-checks) | Uses CPU fixtures/fake daemon where applicable                               |
| Documentation links/index and static dependencies             | [Repository checker](../../scripts/check-repo.py)                                        | Does not prove external link freshness, dynamic imports or runtime isolation |
| Catalog generation, preparation pins and CLI/config reference | [Configuration sync](../../src/video_runners/tools/sync_config.py), run by fast checks   | Checks source agreement, not model availability or hardware compatibility    |
| Formatting and YAML                                           | [Pre-commit configuration](../../.pre-commit-config.yaml)                                | Formatting/syntax, not deployment readiness                                  |
| Supported Compose combinations                                | CI [configuration matrix](../../.github/workflows/ci.yml)                                | Resolution, not engine startup or inference                                  |
| Both modes, switching and proxy isolation                     | [Managed CPU harness](../../tests/e2e/managed.sh), five CI catalog selections            | Real GPU backends are replaced with CPU fixtures                             |

Phase 2 reorganization evidence is recorded in the
[execution plan](../plans/active/harness-refactor.md#verification-log): 108 CPU
checks, all five managed catalog fixtures, bundled integration, wheel installation,
legacy CLI agreement and Compose parity. These checks do not add GPU or paid
coverage to the dated reports below.

Phase 3 evidence in the same plan records **130 CPU tests**, **24 Compose
configurations**, unchanged catalog/manifest bytes and existing CLI help, and a
fresh combined managed CPU fixture pass. Its disposable resources and test image
tags were removed. It adds configuration/reference drift checks without new GPU
or paid-operation claims.

Phase 4 evidence in that plan records **146 CPU tests**, the five managed
selections plus bundled integration (**52 verified fixture clips** in the final
matrix), overlapping runs in separate worktrees, **24 Compose configurations**
and fresh wheel installation. Failure-path resources were safely reconciled;
all run resources, temporary worktrees and disposable raw evidence were removed
following verification. Receipts/leases and correlated logs have CPU coverage;
no new GPU or paid claim follows from those checks. The [validation-run guide](../guides/validation-runs.md)
defines future evidence and cleanup workflows.

The [focused deployment cleanup](../plans/active/deployment-cleanup.md#implementation-and-verification-log)
records the October 16 production/development and retained-mode checks: 152 CPU
tests, 33 Compose configurations, fresh wheel installation and 27 decoded CPU
fixture clips across managed development, production with an owned existing-node
fixture, bundled and external recipes. This adds no GPU or paid-operation evidence.

## Recorded hardware and payment evidence

| Area                                             | Status                         | Evidence and scope                                                                                                                                                                |
| ------------------------------------------------ | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SGLang FastWan 1.3B                              | Recorded GPU pass              | Both modes at 512×288, then 832×480 and 121-frame clips; [initial report](reports/gpu-validation-2026-10-15.md), [workload report](reports/operations-validation-2026-10-15.md)   |
| LightX2V Wan 1.3B                                | Recorded GPU pass              | Same two-mode workload progression; model-specific steps/frame counts in the reports                                                                                              |
| vLLM-Omni Wan 5B                                 | Recorded GPU pass              | Both modes and longer workloads; later profile uses CPU offload and VAE tiling                                                                                                    |
| Cross-engine switching                           | Recorded GPU pass              | Combined catalog switches; observed times, not guaranteed deadlines                                                                                                               |
| Selected recovery behavior                       | Recorded GPU pass              | Twelve recorded cases across three engines, each followed by fresh generation; [case table](reports/operations-validation-2026-10-15.md#recovery-procedure)                       |
| External model volumes and offline reuse         | Recorded host pass             | Download reuse, offline reload, teardown preservation and shared GPU lease; [storage checks](reports/gpu-validation-2026-10-15.md#storage-and-operational-checks)                 |
| Replacement `livepeer/node` signer               | Recorded paid SSE pass         | Three real GPU videos via local signer and direct LAN; [node paid report](reports/node-paid-validation-2026-10-16.md). Paid persistent delivery and settlement remain unvalidated |
| Legacy go-livepeer paid requests                 | Historical compatibility trial | Six verified videos and signed payment batches; [legacy report](reports/paid-validation-2026-10-15.md), outside the supported deployment path                                     |
| Optional LightWan A14B NVFP4 and quality harness | Recorded 480p/720p SDK pilot   | [Quality pilot](reports/video-quality-2026-10-16.md); native workload evidence, human quality confirmation pending                                                                |
| Winning-ticket redemption/final settlement       | Pending                        | Signed batches and generated videos are insufficient evidence                                                                                                                     |

## Pending validation

- Replacement-node orchestrator/signer paid persistent-session delivery; single-shot SSE passed for all three default engines.
- Final settlement, production pricing, public HTTPS and long-duration operation.
- MiniMax-H3, full-precision vLLM Wan A14B and the optional non-distilled SGLang model on hardware. LightWan NVFP4 has separate pilot evidence.
- Human quality review, broader screening/confirmation and vLLM startup-warmup reliability; see the [quality pilot](reports/video-quality-2026-10-16.md).
- Host/daemon outages, runner crashes during active inference and every model-load failure point.
- Multi-GPU behavior, sustained throughput and measured rollback/deadline guarantees.

Use [verification tiers](../reference/checks.md) to repeat or extend these checks.
When a configuration changes, add dated evidence identifying the changed inputs;
do not broaden the meaning of an older report.
