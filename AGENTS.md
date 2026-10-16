# Repository map

This project adapts video engines to Livepeer. Start with
[ARCHITECTURE.md](ARCHITECTURE.md) for components and boundaries, then use the
[documentation index](docs/index.md) to find the relevant instructions.

## Find the work

| Task                                          | Start here                                                                                  |
| --------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Understand the product and CPU quick start    | [README.md](README.md)                                                                      |
| Registration, admission, sessions or delivery | [runner/](src/video_runners/runner)                                                         |
| Engine HTTP APIs and public catalog parsing   | [catalog.py](src/video_runners/catalog.py), [backends/](src/video_runners/backends)         |
| Bundled, external and managed ownership       | [lifecycle/](src/video_runners/lifecycle), [architecture](ARCHITECTURE.md#engine-ownership) |
| Docker policy, state, switching or recovery   | [controller/](src/video_runners/controller)                                                 |
| SDK client or payer-side signer               | [client.py](src/video_runners/client.py), [node guide](docs/guides/node-deployment.md)      |
| Images, weights, volumes or Compose           | [deployment guide](docs/guides/container-deployment.md)                                     |
| Refactor scope and next steps                 | [focused cleanup plan](docs/plans/active/deployment-cleanup.md)                             |
| Proven behavior and remaining checks          | [validation matrix](docs/validation/index.md)                                               |
| Known gaps                                    | [technical debt](docs/plans/tech-debt.md)                                                   |

## Work and verify

- Run `scripts/check.sh` for repository checks, Black, Ruff and CPU unit tests.
  See [check tiers](docs/reference/checks.md) for formatting, Compose and integration.
- Keep runtime changes separate from mechanical moves. Preserve app IDs, routes,
  events, catalog schemas and CLI entry points unless a change is explicitly approved.
- Keep engine/lifecycle/controller code independent of Livepeer. The runner uses
  the controller's authenticated HTTP interface, never its Docker implementation.
  The fast checks enforce the current import boundaries.
- Public request/pricing catalogs and trusted controller launch policies have
  separate authority. See [configuration ownership](ARCHITECTURE.md#configuration-ownership).
- Update the canonical guide when behavior changes. Link new docs from the index.
  Record substantive decisions and evidence in the repository; see
  [core principles](docs/design/core-beliefs.md).
- Run the relevant [validation tier](docs/reference/checks.md) for the change.
  A CPU fixture pass does not establish GPU or paid-operation readiness.

## Host and data constraints

- Routine checks use no Docker daemon, GPU, SSH host or funded signer.
  Deployments, inference and fault injection are separate operator actions.
- On a shared Docker host, act only on verified owned resources. Never prune the
  daemon or disturb unrelated containers. Managed controllers share a GPU lease.
- Preserve external wallet/model/cache volumes, existing host keys and
  `~/.livepeer/keys/`. Never copy credentials into this repository.
- Keep public docs, examples and validation summaries generic. Omit operator
  hostnames, actual addresses, account identities and private resource names;
  retain only the technical inputs needed to understand validation results.
- Do not automatically retry a generation with an unknown outcome.
- Follow [SECURITY.md](SECURITY.md) for trust boundaries and secret handling.
- Follow the current user's commit/deployment scope. Do not push, publish or
  install recurring automation unless requested.

This file is a navigation aid. Detailed operating procedures belong in the
linked documents, not here.
