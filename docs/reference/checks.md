# Verification tiers

Run commands from the repository root. Choose the checks affected by the change
and report exactly what ran. Existing GPU results are evidence for their recorded
versions, not a substitute for checking a changed engine profile.

## Fast local checks

```sh
scripts/check.sh
```

Requires Python 3.12+, `uv` and Git. The command runs:

1. Local documentation links and Markdown heading anchors, reachability of all
   indexed docs, and the current direct/transitive runtime import boundaries.
2. Catalog generation drift, pinned image/asset/launch agreement and the
   source-derived CLI/data reference, using `python3 src/video_runners/tools/sync_config.py`.
3. Black 24.10.0 in check mode and Ruff 0.8.0.
4. The locked development environment's CPU unit and contract tests.

It starts no services, contacts no remote host and uses no Docker daemon, GPU,
model download or signer. The first invocation can download Python dependencies
and lint tools. It may populate normal development caches; it does not rewrite
source files. Tool versions match [pre-commit](../../.pre-commit-config.yaml).

For just repository structure and links:

```sh
python3 scripts/check-repo.py
```

The link checker handles inline links, reference definitions and Markdown heading
anchors; it skips fenced examples and external URLs. It is not a full Markdown
renderer or a semantic documentation audit. The import checker covers static
imports in the package and repository Python modules, including relative imports
and package initializers; it does not prove runtime network access.

For configuration changes, follow the [configuration guide](../guides/configuration.md).
`python3 src/video_runners/tools/sync_config.py --write` refreshes both independently generated
catalogs and the CLI/data reference after source agreement checks. The check mode
does not read private env files or execute the documented commands. It validates
checked-in inputs, not GPU or paid readiness.

## Package installation

CI's `package` job builds a wheel, installs it with the locked core and optional
CPU fixture dependencies into a fresh environment, and invokes all four console
commands outside the checkout. This checks distributable imports and entry
points separately from the editable installation used by fast checks. It starts
no Docker services and performs no model downloads.

## Formatting and deployment configuration

```sh
uvx pre-commit run --all-files --show-diff-on-failure
```

Pre-commit also checks Markdown/JSON/YAML formatting, whitespace, merge markers
and YAML syntax. Its formatting hooks can edit files; inspect the resulting diff.
They need Node/npm for Prettier. The CI `lint` job runs this command.

The CI `compose` job in [ci.yml](../../.github/workflows/ci.yml) runs [the Compose configuration matrix](../../tests/e2e/compose-config.sh). It checks production/development catalogs, ingress attachment, retained bundled/external recipes, preparation and the optional signer without contacting the Docker daemon. It uses placeholder values and `config -q`, never interpolated private settings.

## CPU Docker integration

Use isolated runs for bundled and managed fixtures:

```sh
tests/e2e/bundled.sh
TEST_ENGINE=all tests/e2e/managed.sh
```

Both create run-specific images, ports, networks and state. Managed checks also
exercise restart recovery, proxy denials and network isolation. CI runs all five
managed catalog selections. Cleanup verifies ownership and removes only recorded
test resources, retaining receipts and manifests. These fixtures establish CPU
contract behavior, not GPU compatibility.

Managed CI provisions a pinned Docker daemon and explicitly verifies API v1.51
before building fixtures. Its Buildx context and proxy socket refer to that same
daemon; the hosted image's preinstalled Docker may be too old. Local managed
checks need a compatible daemon already configured, as described in the
[deployment prerequisites](../guides/container-deployment.md).

See [validation runs](../guides/validation-runs.md) for output directories,
receipts, cleanup recovery and concurrent worktrees. The original `tests/e2e/e2e.sh`
still targets an explicitly selected running CPU test stack; it does not own or
clean that deployment. The README's manual quick start retains its normal
project ports and paths.

## Container publication

The explicit [release workflow](../../.github/workflows/release.yml) runs fast
checks, Compose resolution and engine-baseline compatibility on a GitHub-hosted
CPU worker, then checks CPU image entrypoints and publishes digest references.
It reuses matching engine/node digests without pulling GPU layers. Initial or
changed-engine publication is a separate explicit operator action. It is not
part of routine CI or a hardware gate. The [release guide](../guides/container-releases.md)
defines registry credentials, build storage, manifests and pull-only deployment.
Publication starts no inference, signer or paid request. Before a production
release, run the relevant CPU integration and recorded hardware/payment acceptance
checks for changed behavior; a successful image build is insufficient evidence.

## Actual GPU validation

Follow the [deployment guide](../guides/container-deployment.md#generate-inspect-and-switch)
for preparation and the generation/switching commands. These operate a deployed
stack and create videos and receipts. Fault injection is a separate operation on
an idle managed stack connected to the free offchain test node. It interrupts
verified owned resources and rejects priced discovery.

Changes to engine images, launch settings, adapters or workloads need the
relevant hardware check before claiming compatibility. Record the Git revision,
GPU/driver, immutable engine reference, weight revision, workload, delivery mode
and result. Current evidence and gaps are in the [validation matrix](../validation/index.md).

## Paid operation

Follow the [node guide](../guides/node-deployment.md) with an explicitly selected signer
and orchestrator. Routine checks never read existing payer keys or submit paid
work. The [October 16 node trial](../validation/reports/node-paid-validation-2026-10-16.md)
verified paid single-shot SSE for the three default engines. Paid persistent
delivery and final settlement remain separate checks. The historical legacy paid
trial does not establish replacement-node coverage.

## Match checks to the change

| Change                                     | Required evidence                                                                                          |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| Docs, navigation or repository tooling     | Fast checks; pre-commit for formatting; relevant checker regression tests                                  |
| Runtime module move or dependency boundary | Fast checks, wheel installation and affected CPU integration; Compose matrix if paths/builds change        |
| Catalog, adapter or engine image           | Fast checks, affected configuration/CPU contracts and actual hardware validation for compatibility claims  |
| Ownership, switching or recovery           | Fast checks, managed CPU integration and relevant owned-resource hardware recovery cases                   |
| Signer, pricing or payment integration     | Configuration checks plus explicit replacement-node paid validation; settlement requires separate evidence |

Fast checks run in CI's `test` job. Formatting, Compose and Docker integration
retain separate jobs. GPU and paid validation are explicit operator workflows.
