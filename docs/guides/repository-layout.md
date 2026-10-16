# Source layout and command migration

Runtime implementation lives in the installable [src/video_runners/](../../src/video_runners)
package. Run `uv sync --locked` for development. There are no compatibility
symlinks or root Python forwarding modules.

## Canonical commands

| Action                       | Command/source                                                      |
| ---------------------------- | ------------------------------------------------------------------- |
| Run the adapter              | `uv run video-runner`                                               |
| Run the controller           | `uv run video-controller`                                           |
| Submit/list jobs             | `uv run video-client`                                               |
| Run the CPU backend          | `uv run video-stub-engine`                                          |
| Production provider          | `docker compose --env-file /path/to/prod.env -f compose.prod.yml …` |
| Complete development         | `docker compose --env-file /path/to/dev.env -f compose.dev.yml …`   |
| Initialize settings/volumes  | `python3 src/video_runners/tools/init_deployment.py …`              |
| Prepare images               | `python3 src/video_runners/tools/prepare_engines.py …`              |
| Sync catalogs/reference      | `python3 src/video_runners/tools/sync_config.py --write`            |
| Managed Docker integration   | `TEST_ENGINE=all tests/e2e/managed.sh`                              |
| Bundled Docker integration   | `tests/e2e/bundled.sh`                                              |
| Compose configuration matrix | `tests/e2e/compose-config.sh`                                       |
| GPU validation               | `uv run src/video_runners/tools/validate_gpu.py …`                  |

Installed runtime commands also work outside the checkout; supply explicit
catalog/config paths there. The wheel contains Python code, while operator model
catalogs, Compose definitions and deployment settings remain separate files.
The CPU backend requires the optional `stub` dependency group, included by the
default developer installation and stub Docker targets.

## Real sources

- [compose.prod.yml](../../compose.prod.yml) and [compose.dev.yml](../../compose.dev.yml)
  are real root files for the two everyday stacks.
- [deploy/compose/](../../deploy/compose) contains supporting recipes, each with a
  distinct purpose listed in the [deployment guide](container-deployment.md#compose-file-purposes).
  Use `--project-directory .` from the root for these recipes so build/bind paths
  and shared-service references resolve consistently.
- [deploy/docker/](../../deploy/docker) contains Dockerfiles. The upstream node
  build still refers to `docker/Dockerfile` in its own pinned Git context.
- [deploy/templates/](../../deploy/templates) contains real signer/env/tunnel
  examples. The `.service` file is optional and is not installed by this project.
- [src/video_runners/tools/](../../src/video_runners/tools) contains preparation,
  validation, configuration and CPU-harness implementations. Run their real
  paths; no duplicate `scripts/*.py` launchers remain.
- [The external engine launcher](../../src/video_runners/tools/engine_entrypoint.py)
  remains independently mountable and uses only the standard library. GPU engine
  images need no runner package to execute it.
- [tests/e2e/](../../tests/e2e) contains the actual shell harnesses. They create
  isolated owned resources and evidence; see [validation runs](validation-runs.md).
- [scripts/](../../scripts) contains the real fast-check/repository-check scripts.

## Migration from removed paths

| Removed entry point                                                | Replacement                                                                         |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `uv run runner.py`, `controller.py`, `client.py`, `stub_engine.py` | Corresponding `video-*` installed command above                                     |
| Root forwarding imports such as `engines.py`, `lifecycle.py`       | Actual package module from [architecture](../../ARCHITECTURE.md#runtime-components) |
| Root `docker/` alias                                               | `deploy/docker/`                                                                    |
| Root `engine_entrypoint.py`                                        | `src/video_runners/tools/engine_entrypoint.py`                                      |
| `scripts/<hyphenated-tool>.py`                                     | `src/video_runners/tools/<underscored_tool>.py`                                     |
| `scripts/e2e*.sh` aliases                                          | Actual `tests/e2e/` scripts above                                                   |
| `scripts/deploy.sh … init`                                         | Invoke `init_deployment.py` directly with the existing engine/mode options          |
| `scripts/deploy.sh … weights`                                      | Explicit `assets.yml run --rm --build model-tools ENGINE`                           |
| Managed Compose plus existing-node overlays                        | `compose.prod.yml`, with explicit `ingress.yml` when needed                         |
| Managed Compose with demo node                                     | `compose.dev.yml`                                                                   |
| Root bundled/external/GPU Compose aliases                          | Real supporting recipes in `deploy/compose/`                                        |
| Root signer/assets Compose aliases                                 | Real `deploy/compose/signer.yml` and `assets.yml`                                   |
| Config signer/tunnel aliases                                       | Real `deploy/templates/` examples                                                   |

There is no automatic legacy command forwarding. Preserve private env files and
external volumes; change only the invocation and, for external mode, explicitly
set `EXTERNAL_ENGINE_IMAGE`. `ENGINE` selects the public/trusted catalogs in the
managed stacks. Existing runtime flags, models, HTTP routes, delivery modes and
controller state semantics are unchanged.

Historical plans/reports retain their recorded command text. Use current guides
for new runs. [The focused cleanup plan](../plans/active/deployment-cleanup.md)
records the scope and verification; the broader platform proposal remains deferred.
