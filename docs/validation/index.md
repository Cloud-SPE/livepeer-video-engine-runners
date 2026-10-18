# Validation matrix

This is an evidence index, not a claim that a deployment is running. Dated GPU
reports describe the October 15–18, 2026 runs. Earlier deployment-trial videos and
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

The [operator release checks](reports/operator-release-2026-10-17.md) add 249 CPU
tests, 37 Compose configurations, fresh wheel installation, and managed/bundled
Docker checks with 16 decoded fixture clips and verified cleanup. Private metrics
and bounded/explicit-force switching have CPU evidence. No new GPU or paid work
was run. Four-role CPU publication, actual digest pulls and offline entrypoints
also passed; the report records the interrupted earlier engine publication.

The [October 18 acceptance follow-up](reports/operator-acceptance-2026-10-18.md)
records cleanup-race and delivery-drain corrections, 259 CPU tests, 37 Compose
configurations, managed/bundled CI and successful hosted CPU publication/pulls.
All three defaults passed both SDK modes on hardware. Active-work drain, the real
120-second refusal, force, rollback and shutdown cases passed on one GPU. Its
payment section tracks the separate paid checks and settlement evidence.

The separate [free GPU readiness follow-up](reports/gpu-readiness-2026-10-18.md)
checks the new preflight and offline receipt refresh on hardware. All defaults
passed both SDK modes and engine-loss recovery; controlled vLLM starts, active
drain/refusal/force/shutdown and 14 decoded clips passed with verified cleanup.
Cached starts did not reproduce the earlier vLLM timeout; its reliability risk
remains open. Public/paid acceptance was deferred at the operator's request.

| Area                                             | Status                           | Evidence and scope                                                                                                                                                                                                                                          |
| ------------------------------------------------ | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SGLang FastWan 1.3B                              | Recorded GPU pass                | Both modes at 512×288, then 832×480 and 121-frame clips; [initial report](reports/gpu-validation-2026-10-15.md), [workload report](reports/operations-validation-2026-10-15.md)                                                                             |
| LightX2V Wan 1.3B                                | Recorded GPU pass                | Same two-mode workload progression; model-specific steps/frame counts in the reports                                                                                                                                                                        |
| vLLM-Omni Wan 5B                                 | Recorded GPU pass                | Both modes and longer workloads; later profile uses CPU offload and VAE tiling                                                                                                                                                                              |
| Cross-engine switching                           | Recorded GPU pass                | Combined catalog switches; observed times, not guaranteed deadlines                                                                                                                                                                                         |
| Selected recovery behavior                       | Recorded GPU pass                | Twelve recorded cases across three engines, each followed by fresh generation; [case table](reports/operations-validation-2026-10-15.md#recovery-procedure)                                                                                                 |
| External model volumes and offline reuse         | Recorded host pass               | Download reuse, offline reload, teardown preservation and shared GPU lease; [storage checks](reports/gpu-validation-2026-10-15.md#storage-and-operational-checks)                                                                                           |
| Replacement `livepeer/node` signer               | Recorded paid pass in both modes | Nine real GPU videos via local signer/direct LAN, including two-clip sessions for all three defaults; [acceptance report](reports/operator-acceptance-2026-10-18.md#paid-delivery-and-settlement). Twelve winning tickets also reached finalized settlement |
| Legacy go-livepeer paid requests                 | Historical compatibility trial   | Six verified videos and signed payment batches; [legacy report](reports/paid-validation-2026-10-15.md), outside the supported deployment path                                                                                                               |
| Optional LightWan A14B NVFP4 and quality harness | Recorded SDK pilot and screening | [Quality pilot](reports/video-quality-2026-10-16.md) and [screening review](reports/video-quality-screening-2026-10-16.md#screening-human-review); human screening complete, held-out confirmation pending                                                  |
| Winning-ticket redemption/final settlement       | Recorded finalized pass          | Twelve successful canonical finalized receipts, matching redemption events and zero unsettled tickets; [acceptance evidence](reports/operator-acceptance-2026-10-18.md#paid-delivery-and-settlement)                                                        |

The [resolution screening and duration report](reports/video-quality-screening-2026-10-16.md)
records both human reviews, 32 controlled LightWan clips, native 10/15-second
delivery, the failed 20-second request and an assembled 30-second sequence.

The [standard Wan A14B quality trial](reports/video-quality-wan-a14b-2026-10-16.md)
records the active-request health-probe fix, a host-memory failure and three
successful BF16/lazy-loading SDK clips. The operator intentionally stopped the
fourth request, then reviewed the three completed pairs: one win each and one
tie, with all six clips usable. No consistent quality preference is established;
the hard-scene comparisons and new perceptual scores were not completed. Owned
test deployment/staging cleanup is verified; protected external data is retained.

The operator resumed the [three-scene follow-up](reports/video-quality-wan-hard-scenes-2026-10-17.md)
after a regression-tested managed-shutdown correction. The three difficult scenes
use existing LightWan references. All three new deliveries, six offline metrics,
the hardware recovery/shutdown case and cleanup passed. The three-pair gallery
is verified. Human review preferred standard Wan for objects and rain, and
LightWan for pouring, despite an extra hand in that preferred reference. The
candidate's three clips were marked usable; one reference usability field is
unanswered. Further seeds and held-out confirmation remain pending, with no
default change. That follow-up passed 202 CPU tests; the latest acceptance checks
are recorded separately above.

## Pending validation

The [operator readiness follow-up](reports/operator-readiness-2026-10-18.md)
adds CPU preparation/payment-policy checks and an immutable upstream timeout
comparison. It changes no engine pins and adds no GPU or paid-readiness claim.

- Production pricing/ticket economics, public node HTTPS and sustained public operation.
- MiniMax-H3, full-precision vLLM Wan A14B and the optional non-distilled SGLang model on hardware. LightWan NVFP4 has separate pilot evidence.
- Held-out quality confirmation, whole-clip human review of the longer examples,
  memory-saving 20–30-second continuous generation and vLLM startup-warmup reliability; see the [screening report](reports/video-quality-screening-2026-10-16.md).
- Host/daemon outages, runner crashes during active inference and every model-load failure point.
- Multi-GPU behavior, sustained throughput and exhaustive rollback/deadline guarantees.
  The agreed single-GPU drain/timeout/force/rollback/shutdown cases have recorded
  [acceptance evidence](reports/operator-acceptance-2026-10-18.md#active-work-switching-and-shutdown).

Use [verification tiers](../reference/checks.md) to repeat or extend these checks.
When a configuration changes, add dated evidence identifying the changed inputs;
do not broaden the meaning of an older report.
