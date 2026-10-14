# Contributing

Thanks for helping. The most valuable contributions right now are **GPU validation reports**, **catalog entries for new models**, and **new engines**; bug fixes and documentation are always welcome.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately as described in [SECURITY.md](SECURITY.md), not in issues.

## Before you start

- **Small fixes** (typos, docs, obvious bugs): open a pull request directly.
- **Anything larger** (new engine, new delivery behavior, API or catalog schema changes): open an issue first so we can agree on the approach. Changes to app ids, endpoints, event shapes, catalog keys or CLI flags are breaking (see [Versioning](#versioning)).
- **GPU reports and model requests:** use the [engine or model](.github/ISSUE_TEMPLATE/engine_or_model.yml) issue form.

## Development setup

You need Docker (Compose v2), [uv](https://docs.astral.sh/uv/) and git. A GPU is not needed for most work: the stub engine covers the network path.

```sh
git clone https://github.com/Cloud-SPE/livepeer-video-engine-runners.git
cd livepeer-video-engine-runners
uv sync                     # Python environment including dev tools
uvx pre-commit install      # format and lint on every commit
```

## Checks

Run these before opening a pull request; CI runs the same ones.

```sh
uvx pre-commit run --all-files                          # black, ruff, prettier, whitespace
uv run pytest                                           # unit tests
ENGINE=stub docker compose up -d --build --wait         # orchestrator + stub runner
scripts/e2e.sh                                          # discovery, both modes, model switch
docker compose down
```

For changes to an engine client, an engine image or a catalog, also run the real engine on a GPU and paste the results in the PR: GPU and VRAM, driver/CUDA, image tag, model, resolution, frames, steps, load time, seconds per clip and peak VRAM.

## Writing code

- Follow the [conventions in the README](README.md#conventions). In short: `engines.py` stays free of Livepeer code; SDK calls in `runner.py` and `client.py` carry a `# Livepeer: n` marker; Python 3.12 with type hints; `black` and `ruff` clean.
- Match the surrounding code: naming, comment density, and comments that explain _why_.
- Keep model-specific settings in catalogs (`models/*.json`) and engine configs (`configs/`), not in code.
- Add or update tests with behavior changes. Engine clients are tested against `stub_engine.py`; extend the stub when an engine gains an API feature you rely on.
- Pin new external inputs (images, sources, actions, dependencies). Update `uv.lock` with `uv lock` when dependencies change.
- Never commit secrets, `.env` files, model weights or generated videos.

## Commits and pull requests

- Commit summaries are imperative and sentence case and say what changes for the reader, e.g. `Release abandoned sessions after an idle timeout`. Use the body for the why. One logical change per commit.
- Keep pull requests focused. Fill in the PR template, including how you tested.
- Update `README.md`, `.env.example` and the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md) when behavior or configuration changes.
- A maintainer reviews every PR; CI must pass before merge. We squash or rebase-merge to keep history linear.

## Adding a model

1. Add an entry to `models/<engine>.json`: a lowercase, engine-agnostic `id` (e.g. `wan2.2-ti2v-5b`), the engine `command`, request `defaults` the model supports, and timeouts that cover download, load and one clip.
2. Run it on a GPU through the runner (both delivery modes) and include the report in the PR.
3. Add the model to the README's engine table.

## Adding an engine

See [Adding an engine](README.md#adding-an-engine) in the README. The engine must expose an asynchronous job API (submit, status, result, cancel) and a health endpoint, and run headless on `127.0.0.1`.

## Versioning

The project follows [Semantic Versioning](https://semver.org/). The public contract is: app ids, runner endpoints, SSE and JSONL event shapes, catalog keys, and runner/client CLI flags. Breaking any of them requires a major version (a minor version while we are at 0.x) and a clear CHANGELOG entry.

## Releasing (maintainers)

1. Move `Unreleased` entries in `CHANGELOG.md` under the new version and date.
2. Bump `version` in `pyproject.toml` and run `uv lock`.
3. Tag `vX.Y.Z` on `main` and create a GitHub release from the changelog section.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
