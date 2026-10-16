# Harness-oriented repository refactor

Status: Phases 1–4 complete. This file retains the original plan path for existing links and records the execution evidence. Baseline implementation: `f3bc0c3`; IDE ignore
cleanup: `3436d8a`. All commits remain local unless the operator requests a push.

The later [focused cleanup](deployment-cleanup.md) removed the compatibility
aliases and deployment wrapper retained in Phase 2. Statements about those
paths and commands below describe the original phase, not current deployment
instructions. Current commands are in the [layout guide](../../guides/repository-layout.md),
and current paid/GPU coverage is in the [validation matrix](../../validation/index.md).

## Objective and constraints

Make this project easy to navigate, verify and safely change using the
[core principles](../../design/core-beliefs.md). Preserve existing application
behavior through the reorganization.

- Preserve app IDs, endpoints, event shapes, catalog schemas and CLI entry points.
- Keep bundled mode supported during the refactor; retirement is a separate decision.
- Preserve public/trusted configuration authority and shared-host isolation.
- Keep existing external wallet/model/cache volumes and host keys untouched.
- Do not deploy services, run GPU/paid work or install recurring automation as
  part of Phase 1. Routine checks need no Docker daemon or remote host.
- Commit each phase separately. Do not mix mechanical moves with behavior fixes.

## Phase 1: map and verification

- [x] Add a short agent map, current architecture guide and documentation index.
- [x] Record principles, this execution plan, technical debt and validation status.
- [x] Add a fast command for repository checks, Black, Ruff and CPU tests.
- [x] Check local documentation links/anchors, doc reachability and current
      static dependency boundaries, with actionable errors and regression checks.
- [x] Configure CI to run the same fast command and link it from contributor instructions.
- [x] Verify and record results; include this plan in the local Phase 1 commit.

Exit: a contributor can find the implementation, run checks and distinguish
recorded behavior from pending validation. No runtime module or deployment path moves.

## Phase 2: mechanical reorganization

The operator approved this phase after reviewing Phase 1. The implementation now
uses the following layout; exact compatibility mappings are in the
[layout guide](../../guides/repository-layout.md).

```text
src/video_runners/
  catalog.py
  backends/
  lifecycle/
  runner/
  controller/
  client.py
  tools/
deploy/
  compose/
  docker/
  templates/
models/
configs/
docs/
  guides/
  design/
  plans/
  reference/
  validation/
tests/
  unit/
  integration/
  e2e/
scripts/
```

- [x] Introduce the installable package without upgrading runtime dependencies.
- [x] Split engine contracts/adapters, lifecycle supervision, runner and controller
      responsibilities while preserving original function/method bodies.
- [x] Retain root Python compatibility facades and standard-library engine launcher.
- [x] Move deployment sources and retain symlink aliases for existing commands.
- [x] Group CPU unit/local integration tests and explicit Docker harnesses.
- [x] Group guides, design records and historical evidence; update links and maps.
- [x] Extend import checks for package-relative imports and package initializers.
- [x] Add CLI/standalone-launcher regression coverage and an installed-wheel CI job.
- [x] Finish Compose/CPU end-to-end verification and record results for the local Phase 2 commit.

The deployment wrapper sets an explicit repository-root Compose project directory.
Public/trusted catalogs, volumes, image/asset pins and runtime flag defaults stay
unchanged. Existing command names remain available through compatibility entries.

Exit: fast checks, the affected Compose matrix and CPU integration pass. Review
the exact command/path migration before changing existing operator workflows.

## Phase 3: configuration consistency

Generate the combined public catalog from per-engine public catalogs. Independently
generate the combined trusted catalog from per-engine controller policies.
Keep pinned image/asset manifests authoritative for preparation and validate
their agreement with launch policy. Public request overrides never become
executable policy at runtime.

Consolidate repeated tooling with explicit inputs. Extend import rules to the
package layout and add configuration/reference drift checks based on the settled
schemas and CLI. Avoid broad shared helpers that hide authority or side effects.

- [x] Generate public and trusted combined catalogs through independent readers.
- [x] Check immutable preparation pins, model IDs/defaults and launch agreement.
- [x] Generate public data/CLI reference from source without reading private settings.
- [x] Share literal env parsing and checked output capture in host tools.
- [x] Add fast-check and regression coverage for drift and authority separation.
- [x] Finish verification and record evidence for the local Phase 3 commit.

The [configuration guide](../../guides/configuration.md) owns the regeneration
workflow. Both generated JSON catalogs remain byte-for-byte identical to the
Phase 2 versions. New checks and references describe the existing contracts;
they do not change deployed engine launch policy or request defaults.

Exit: CI rejects generated/configuration drift and prohibited dependencies;
current behavioral contracts and applicable integration checks still pass.

## Phase 4: operational feedback

Add worktree/run-specific resource and image identities, owned-resource cleanup
manifests, consistent machine-readable receipts and correlated lifecycle logs.
Record Git revision, engine image, asset revision, workload and result without
secrets. Reuse external model volumes and serialize hardware checks on the
reserved GPU. GPU/paid validation remains an explicit operator workflow.

- [x] Give bundled/managed CPU tests per-worktree/run images and resources.
- [x] Record Docker identities/fingerprints and verify owned-resource cleanup.
- [x] Add versioned validation receipts with source, pins, workload and result.
- [x] Coordinate parent/child hardware validators through a shared host lease.
- [x] Correlate managed lifecycle logs without changing protocol/state schemas.
- [x] Finish cross-worktree Docker, package/configuration and documentation verification.
- [x] Record evidence for the local Phase 4 commit; do not push.

Exit: a run can identify its inputs, outcome and owned resources; independent
CPU worktrees do not overwrite each other's images or state. Hardware/payment
claims require fresh evidence, not a documentation status change.

## Decisions

| Date       | Decision                                                      | Reason                                                                                                    |
| ---------- | ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 2026-10-15 | Start with Phase 1 and review before moving runtime code      | Establish a map and checks before changing imports or deployment paths                                    |
| 2026-10-15 | Keep one Python project and preserve deployed role boundaries | Runner and controller need independent runtime authority, not additional service decomposition            |
| 2026-10-15 | Retain separate public and trusted catalog sources            | Request/pricing changes must not grant Docker launch authority                                            |
| 2026-10-15 | Keep GPU and paid checks outside the fast command             | Routine verification must not use shared-host GPU resources or funded keys                                |
| 2026-10-15 | Proceed with Phase 2 after the operator reviewed Phase 1      | Package and reorganize code while preserving operator commands and behavior                               |
| 2026-10-15 | Retain deployment/script symlinks and Python runtime facades  | Keep one canonical implementation while preserving existing Linux commands                                |
| 2026-10-15 | Proceed with Phase 3 after operator approval                  | Remove catalog duplication and enforce configuration/reference agreement without changing launch behavior |

## Verification log

Phase 1, 2026-10-15:

- `scripts/check.sh` passed: repository navigation/anchors/import boundaries,
  Black, Ruff and **100 CPU tests**, including six checker cases. The fixtures
  exercise nested/reference links, duplicate headings, fenced examples, missing
  targets/anchors, unindexed docs, transitive authority leaks and permitted imports.
- Prettier 3.3.3 check and the pinned YAML, merge-marker, whitespace and EOF hooks
  passed when run directly. `git diff --check` and shell syntax/help checks passed.
- The link check exposed a stale README weights-section anchor; it was corrected.
- Runtime Python modules, Compose files, Dockerfiles, model/config data and the
  dependency lock were unchanged. No Docker, SSH, GPU or paid workflow was run.

Phase 2, 2026-10-15:

- `scripts/check.sh` passed with **108 CPU tests**, including package-relative and
  initializer import checks, legacy/installed CLI agreement and a launcher check
  with Python site packages disabled. The legacy engine-preparation command also
  runs directly from outside the checkout; executable modes/shebangs were audited
  against the Phase 1 tree.
- All **140 original runtime function/method ASTs** remain present unchanged in
  the package. All **11 legacy CLI help outputs** match the pre-move baseline.
- **23 Compose configurations** match their pre-move baselines except the intended
  local Dockerfile paths. **10 direct canonical-file invocations** also match the
  corresponding legacy invocations, including bundled GPU overlays and signer.
- Bundled CPU Docker integration passed through legacy paths. Managed CPU Docker
  integration passed for `stub`, `sglang`, `lightx2v`, `vllm-omni` and `all`,
  including both delivery modes, switching, restart recovery and proxy isolation.
- The wheel builds and installs into a fresh environment. Three core commands
  pass outside the checkout; the stub command also passes with its locked optional
  fixture dependencies. CI has a matching wheel smoke job.
- The model-tools image resolves all three pinned default plans with networking
  disabled and no model downloads.
- Runtime dependency lock entries, public/trusted catalogs, asset/image pins,
  volume settings and persisted controller state schema were unchanged. The lock's
  only package-entry change is the project's virtual-to-editable install mode.
- Disposable CPU stacks, temporary state volumes and task-built image tags were
  removed after verification; the shared daemon was not pruned.
- No GPU inference, SSH deployment or paid operation was run. Dated GPU/payment
  reports retain their original scope; replacement-node paid validation was
  pending at this phase. See the current validation matrix for later evidence.

Phase 3, 2026-10-15:

- `scripts/check.sh` passed with **130 CPU tests**. New cases reject stale
  generated files, conflicting trusted headers, image/asset/default/path drift,
  duplicate model IDs and prohibited application imports in configuration helpers.
  They also verify public/trusted generation separation, AST-derived CLI/policy
  reference changes, literal env values, and preservation of completed image
  staging after a later failure.
- Both combined JSON files and both pinned input manifests remain byte-for-byte
  unchanged. All **11 existing CLI help outputs** match their pre-phase baselines.
  Four host tools also run with Python site packages disabled from outside the
  checkout; the standalone engine launcher retains its separate regression check.
- **24 Compose configurations** resolved using placeholder credentials, covering
  bundled/GPU overlays, managed/external modes, existing-node connectivity, asset
  preparation and the optional signer. Deployment definitions were unchanged.
- `TEST_ENGINE=all scripts/e2e-managed.sh` passed both delivery modes, switching
  between SGLang-shaped and LightX2V-shaped CPU fixtures, controller/runner restart
  recovery, denied Docker routes and private endpoint isolation. Phase 2's five
  catalog-selection runs remain separate evidence; this phase repeated the
  combined selection only.
- Prettier 3.3.3 and the pinned YAML/merge-marker/whitespace/EOF checks passed;
  `git diff --check` passed. Fast checks now include read-only configuration sync,
  so CI's existing `test` job also rejects generated/reference drift.
- The disposable managed project, its temporary volumes and all four task-built
  image tags were removed. Unrelated Docker workloads remained running; the
  daemon was not pruned. No SSH, GPU inference, model download or paid workflow
  ran, and external model/wallet volumes and existing keys were untouched.

Phase 4, 2026-10-15:

- `scripts/check.sh` passed with **146 CPU tests**. New coverage checks private,
  unique receipts, partial/unknown outcomes, single submission after failure,
  inherited host leases, credential-field rejection/redaction, immutable image
  identity, daemon/configuration/volume ownership, idempotent cleanup and durable
  managed-engine classification despite inherited Compose labels. The existing
  lost-response test also verifies one operation ID across runner/controller logs.
- All **five managed catalog selections** and the bundled harness passed. The
  final matrix decoded **52 fixture clips** across both delivery modes, switching,
  managed runner/controller restarts, proxy denials and network isolation.
- Bundled and combined managed runs overlapped in distinct worktrees. Receipts
  confirmed different worktree/run IDs, independent images/resources and completed
  cleanup. Separate managed runs covered stub, SGLang, LightX2V and vLLM-Omni.
  Worktree-derived identifiers are omitted from this public execution record.
- Failure-path trials also exercised unhealthy startup and fail-closed ownership
  checks. Fixture-catalog read permissions, inherited Compose labels and truncated
  Docker IDs were corrected. Retained resources were reconciled through the
  verified cleanup command; failed work remains marked failed, with cleanup
  independently recorded as complete.
- **24 canonical Compose configurations** resolved. The wheel built and installed
  into a fresh environment; all four runtime commands passed outside the checkout.
  Formatting, YAML, whitespace/EOF and merge-marker checks passed.
- **16 controller/managed-supervisor methods** match Phase 3 after removing the
  added diagnostic/context statements. Existing **11 CLI option declarations**,
  public/trusted catalogs, image/asset pins, dependency declarations/lock and
  production deployment sources were unchanged. HTTP/event/state schemas remain
  covered by existing contracts.
- The [validation-run guide](../../guides/validation-runs.md) documents receipt
  schema, expected versus inspected inputs, cleanup recovery, host lock scope and
  CI artifact selection. CI now uses isolated harnesses and retains only selected
  JSON evidence through a commit-pinned action. Remote CI was not triggered.
- Run-specific Docker resources/images and the temporary worktree were removed.
  Disposable verification videos, receipts and logs were inspected, summarized
  here, then removed for the operator's cleanup preference. Normal BuildKit caches
  and unrelated Docker workloads were preserved; the daemon was not pruned.
- No SSH deployment, GPU inference, weight download, paid request or funded-key
  access ran. External wallet/model/cache volumes remain untouched. New hardware
  lease/receipt behavior has CPU tests; actual GPU/paid validation remains an
  explicit future operator workflow, with the previous gaps unchanged.

These are local results; remote CI was not triggered because nothing was pushed.
Refer to the [check tiers](../../reference/checks.md) and
[validation matrix](../../validation/index.md) for scope. The
[debt tracker](../tech-debt.md) records remaining work.
