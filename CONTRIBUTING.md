# Contributing

Thanks for helping. The most valuable contributions right now are **GPU validation reports**, **catalog entries for new models**, and **new engines**; bug fixes and documentation are always welcome.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately as described in [SECURITY.md](SECURITY.md), not in issues.

## Before you start

- **Small fixes** (typos, docs, obvious bugs): open a pull request directly.
- **Anything larger** (new engine, new delivery behavior, API or catalog schema changes): open an issue first so we can agree on the approach. Changes to app ids, endpoints, event shapes, catalog keys or CLI flags are breaking (see [Versioning](#versioning)).
- **GPU reports and model requests:** use the [engine or model](.github/ISSUE_TEMPLATE/engine_or_model.yml) issue form.

## Development setup

Start with the [repository map](AGENTS.md), [architecture](ARCHITECTURE.md) and [documentation index](docs/index.md). The [focused cleanup record](docs/plans/active/deployment-cleanup.md) records the completed compatibility and Compose changes; the earlier refactor record is historical.

Fast checks need Python 3.12+, [uv](https://docs.astral.sh/uv/) and Git. Docker with Compose is needed for integration and deployment, and Node/npm for the Prettier hook. A GPU is not needed for CPU contract tests or stub integration.

```sh
git clone https://github.com/Cloud-SPE/livepeer-video-engine-runners.git
cd livepeer-video-engine-runners
uv sync                     # Python environment including dev tools
uvx pre-commit install      # format and lint on every commit
```

## Checks

Run fast checks before opening a pull request. CI's `test` job runs the same command; formatting, Compose and integration have separate jobs. The [check tiers](docs/reference/checks.md) describe their scope and required evidence.

```sh
uvx pre-commit run --all-files                          # black, ruff, prettier, whitespace
scripts/check.sh                                       # links, boundaries, Black, Ruff and CPU tests
tests/e2e/bundled.sh                                  # isolated bundled CPU Docker run
```

Use `TEST_ENGINE=all tests/e2e/managed.sh` for managed lifecycle/integration changes. Both wrappers retain versioned receipts and verified cleanup manifests; see [validation runs](docs/guides/validation-runs.md). Do not run GPU, fault-injection or paid validation as part of routine local checks. Use the appropriate explicit workflow and record its evidence in the [validation matrix](docs/validation/index.md).

For changes to an engine client, an engine image or a catalog, also run the real engine on a GPU and paste the results in the PR: GPU and VRAM, driver/CUDA, image tag, model, resolution, frames, steps, load time, seconds per clip and peak VRAM.

## Writing code

- Follow the [conventions in the README](README.md#conventions). In short: package contracts/backends/lifecycle/controller stay free of Livepeer code; SDK calls in `src/video_runners/runner/` and `client.py` carry a `# Livepeer: n` marker; Python 3.12 with type hints; `black` and `ruff` clean.
- Match the surrounding code: naming, comment density, and comments that explain _why_.
- Keep model-specific settings in catalogs (`models/*.json`) and engine configs (`configs/`), not in code.
- Edit per-engine catalog sources and regenerate combined catalogs/reference with `python3 src/video_runners/tools/sync_config.py --write`; see the [configuration guide](docs/guides/configuration.md). Review public request settings and trusted launch policy separately.
- Add or update tests with behavior changes. Engine clients are tested against `src/video_runners/stub_engine.py`; extend the stub when an engine gains an API feature you rely on.
- Pin new external inputs (images, sources, actions, dependencies). Update `uv.lock` with `uv lock` when dependencies change.
- Never commit secrets, `.env` files, model weights or generated videos.
- Keep documentation and public validation summaries independent of an operator's infrastructure. Use example domains and documentation-only IPs for host addresses; label Docker subnet examples. Omit real hostnames, usernames, account addresses, GPU UUIDs, private paths and resource names. Preserve useful model/image/version/workload evidence without publishing raw private receipts or logs.

## Commits and pull requests

- Commit summaries are imperative and sentence case and say what changes for the reader, e.g. `Release abandoned sessions after an idle timeout`. Use the body for the why. One logical change per commit.
- Keep pull requests focused. Fill in the PR template, including how you tested.
- Update `README.md`, `.env.example` and the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md) when behavior or configuration changes.
- A maintainer reviews every PR; CI must pass before merge. We squash or rebase-merge to keep history linear.

## Adding a model

1. Add an entry to `models/<engine>.json`: a lowercase, engine-agnostic `id` (e.g. `wan2.2-ti2v-5b`), the engine `command`, request `defaults` the model supports, and timeouts that cover download, load and one clip.
2. Add its independently reviewed trusted controller template and pinned asset plan. Follow the [configuration guide](docs/guides/configuration.md), regenerate combined catalogs, and run the affected CPU checks.
3. Run it on a GPU through the runner (both delivery modes) and include the report in the PR.
4. Add the model to the README's engine table.

## Adding an engine

See [Adding an engine](README.md#adding-an-engine) in the README. The engine must expose an asynchronous job API (submit, status, result, cancel) and a health endpoint, and run headless. Bundled engines bind to `127.0.0.1`; separate engine containers bind to their private network without publishing a host port.

## Versioning

The project follows [Semantic Versioning](https://semver.org/). The public contract is: app ids, runner endpoints, SSE and JSONL event shapes, catalog keys, and runner/client CLI flags. Breaking any of them requires a major version (a minor version while we are at 0.x) and a clear CHANGELOG entry.

## Releasing (maintainers)

1. Move `Unreleased` entries in `CHANGELOG.md` under the new version and date.
2. Bump `version` in `pyproject.toml` and run `uv lock`.
3. Tag `vX.Y.Z` on `main` and create a GitHub release from the changelog section.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
