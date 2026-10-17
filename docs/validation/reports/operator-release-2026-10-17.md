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

Two additional regressions first reproduced an admin switch activating a
replacement after shutdown and acceptance of a new switch while closing.
Shutdown now cancels the in-flight runner switch before final deactivation and
refuses new switches. Both regressions passed with the correction; accepted
controller operations still use managed shutdown's bounded reconciliation.

## Verification results

| Check                                                          | Result                                                                                                                                 |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Fast repository/configuration/import/Black/Ruff/CPU suite      | 249 tests passed                                                                                                                       |
| Formatting, whitespace, YAML and merge markers                 | Passed on changed files                                                                                                                |
| Compose configuration matrix                                   | 37 configurations resolved                                                                                                             |
| Fresh wheel installation and four entrypoints outside checkout | Passed                                                                                                                                 |
| Combined managed CPU deployment                                | Passed: both delivery modes, switching, explicit forced reload, metrics auth, recovery and proxy/network isolation; nine decoded clips |
| Bundled CPU deployment                                         | Passed: both delivery modes and switching; seven decoded clips                                                                         |
| Owned integration-resource cleanup                             | Both receipts verified complete                                                                                                        |
| Public documentation/configuration privacy review              | No operator host/account/address/resource identifiers added                                                                            |

A subsequent managed rerun during heavy local image extraction failed when
the Docker stop API exceeded its 60-second transport timeout. Admission stayed
closed. A rollback create completed late, after teardown had inspected owned
resources. Automatic cleanup refused the resulting unrecorded stopped fixture.
Manual review verified its unique test image, full trusted launch policy, name
and non-running state before removal; cleanup then verified complete. The failed
receipt is retained. No ownership checks or timeouts were weakened. This exposes
[HARNESS-03](../../plans/tech-debt.md). After extraction ended, a fresh clean-source
managed run at `b4357a2` passed with nine decoded clips and complete cleanup.
The updated-source bundled rerun passed with seven decoded clips and complete
verified cleanup. No GPU or unrelated workload was touched.

CPU run receipts retain exact source revisions, dirty-worktree indications and
individual workload/cleanup evidence privately. The latest managed receipt is
from a clean committed checkout; the bundled rerun used `f46f3c3`, whose runtime
source matches `b4357a2`. No new GPU or paid request
was submitted. Existing hardware/payment evidence remains scoped to its original
image/source/configuration.

## CPU release boundary and publication status

Operators prepare GPU engines and weights on their own hosts. Application
publication is limited to four CPU roles: runner, controller, model-tools and
pinned node. Its version-2 CPU manifest/env never supplies engine references.
CPU pulls stage only those four images, preserving `.engine-images.env` and
external data. Optional prior-manifest reuse applies only to a matching node;
no previous manifest or engine baseline is required for an initial CPU release.

The initial `0c33f45` attempt published four CPU images, which passed actual
registry-digest pulls, image/source-label matching and offline entrypoint checks.
That attempt also built a roughly 36 GiB LightX2V image and began an engine
upload. The upload was stopped after the operator clarified the release boundary.
The old combined attempt is retained as failed evidence and produced no complete
deployment env. Its format and engine publication path are removed from the
current publisher. The operator's existing local LightX2V preparation recipe is
unchanged. No registry or daemon pruning was performed.

The corrected path has 25 release unit cases passing. An acceptance regression
first reproduced the unwanted LightX2V build in a normal application release.
Tests now verify cold CPU publication, exact CPU-only env/pulls, missing engine
build files, preservation of operator settings, node provenance and refusal of
combined GPU bundles before any Docker action. Deliberately removing the CPU
publication guard and adding an engine pull each made its protective test fail;
the production source was restored. Earlier GPU-baseline assertions were replaced
because that release requirement was explicitly retired, rather than weakened
as a workaround for a failure.

The corrected CPU-only path passes all 249 CPU tests and 37 Compose
configurations. Corrected registry publication will be recorded after its
digest-pull and entrypoint verification. Operating instructions remain generic
in the [release guide](../../guides/container-releases.md). The manually triggered
hosted CPU workflow is prepared; remote activation and registry settings/secrets
are separate actions. Optional node reuse does not require an engine baseline.
No self-hosted build-worker service was installed.
