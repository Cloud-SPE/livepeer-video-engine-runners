# Operator release and lifecycle checks — 2026-10-17

This records the scoped release/metrics/switching work in the
[execution plan](../../plans/active/operator-release.md). GPU work remains
stopped. The hardware host was inspected read-only: no video trial container or
staging directory remained, six protected external volumes remained present,
and unrelated workloads/services were left untouched. No model/cache/wallet/key
data was removed and no daemon prune was used.

## Runtime behavior and regression evidence

The baseline passed 202 CPU tests. New tests first demonstrated missing private
metrics, outcome/refusal/recovery counters, drain timeout and explicit force
behavior. The force HTTP flag is strictly boolean. A regression reproduced a
persistent task cancelled before it could enter its cleanup block; the fix releases
that reservation after verified owned-engine stop. Existing tests/assertions
were retained; CPU harnesses add checks for private metrics and forced switching.

Graceful drain defaults to 120 seconds. Timeout preserves active work and its
registration. Explicit force cancels the active task, confirms owned-engine
termination and completes task cleanup before activating another model. An
unavailable stop or timeout leaves recovery required and admission closed.
Deliberately skipping stop verification made both protective tests fail; the
production source was restored. Model-load/rollback bounds remain profile-specific.
This is CPU evidence, not fresh hardware timing or fault-injection evidence.

## Verification results

| Check                                                          | Result                                                                                                                                 |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Fast repository/configuration/import/Black/Ruff/CPU suite      | 235 tests passed                                                                                                                       |
| Formatting, whitespace, YAML and merge markers                 | Passed on changed files                                                                                                                |
| Compose configuration matrix                                   | 37 configurations resolved                                                                                                             |
| Fresh wheel installation and four entrypoints outside checkout | Passed                                                                                                                                 |
| Combined managed CPU deployment                                | Passed: both delivery modes, switching, explicit forced reload, metrics auth, recovery and proxy/network isolation; nine decoded clips |
| Bundled CPU deployment                                         | Passed: both delivery modes and switching; seven decoded clips                                                                         |
| Owned integration-resource cleanup                             | Both receipts verified complete                                                                                                        |
| Public documentation/configuration privacy review              | No operator host/account/address/resource identifiers added                                                                            |

CPU run receipts retain the source base plus dirty-worktree indication and
individual workload/cleanup evidence privately. Their images used the current
implementation before the local source checkpoint. No new GPU or paid request
was submitted. Existing hardware/payment evidence remains scoped to its original
image/source/configuration.

## Container publication status

The publisher is implemented with pinned inputs, CPU entrypoint checks,
registry digest receipts, a complete-release env and a guarded pull command.
It preserves completed-image evidence if later publication fails. Unit tests
verify role separation, invalid/credential-bearing inputs, digest-only output,
incomplete-manifest refusal and preservation of existing deployment settings.

Actual registry publication is pending the clean local source checkpoint and
the ongoing local base-image preparation. No images are claimed published here
yet. The manually triggered GitHub workflow is prepared; its separate build
worker, registry settings/secrets and remote activation are not implied by a
successful local build. Operating instructions remain generic in the
[release guide](../../guides/container-releases.md).
