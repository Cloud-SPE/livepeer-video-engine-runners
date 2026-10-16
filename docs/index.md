# Documentation map

Use the guide for the task you are performing. Historical reports describe
observed runs; current guides describe how to deploy the checked-in code.

| Need                                             | Source of truth                                                  |
| ------------------------------------------------ | ---------------------------------------------------------------- |
| Product overview and CPU quick start             | [README](../README.md)                                           |
| Agent navigation and working constraints         | [AGENTS](../AGENTS.md)                                           |
| Current components, dependencies and ownership   | [Architecture](../ARCHITECTURE.md)                               |
| Engine deployment, weights, volumes and recovery | [Container deployment](guides/container-deployment.md)           |
| Node orchestrator, signer and Python SDK         | [Node deployment](guides/node-deployment.md)                     |
| Source layout and command migration              | [Repository layout](guides/repository-layout.md)                 |
| Catalog sources, generated files and pin updates | [Configuration](guides/configuration.md)                         |
| Python CLI arguments and public data fields      | [Generated reference](reference/configuration.md)                |
| Commands and required verification tiers         | [Checks](reference/checks.md)                                    |
| Isolated test runs, receipts, cleanup and logs   | [Validation runs](guides/validation-runs.md)                     |
| Tested behavior and pending validation           | [Validation matrix](validation/index.md)                         |
| Development and contribution workflow            | [Contributing](../CONTRIBUTING.md)                               |
| Trust boundaries and secret handling             | [Security](../SECURITY.md)                                       |
| Engineering principles                           | [Core principles](design/core-beliefs.md)                        |
| Historical refactor execution evidence           | [Execution record](plans/active/harness-refactor.md)             |
| Compatibility and prod/dev Compose cleanup       | [Focused cleanup](plans/active/deployment-cleanup.md)            |
| Deferred broader provider-platform discussion    | [Full discussion record](plans/deferred/provider-platform-v1.md) |
| Known gaps and follow-up work                    | [Technical debt](plans/tech-debt.md)                             |
| Engine-container design and rollout history      | [Engine rollout](design/engine-container-rollout.md)             |

Keep operating procedures in their guide, architecture in the architecture map
and dated evidence in reports linked from the validation matrix. Add new docs to
this navigation graph. The repository checker rejects broken local links,
missing Markdown heading anchors and documentation that cannot be reached from
this index. It does not verify external websites or the factual freshness of prose.

Guides, design records and validation reports have separate directories. The
[layout guide](guides/repository-layout.md) maps canonical sources and removed commands to their replacements. The focused
cleanup plan records completed work; the broader provider-platform plan is deferred.
