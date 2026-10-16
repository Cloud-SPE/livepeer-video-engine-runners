#!/usr/bin/env bash
# Fast local checks. No Docker, GPU, deployment or paid requests.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -gt 0 ]; then
  echo 'Usage: scripts/check.sh (repository checks, Black, Ruff and CPU tests)' >&2
  if [ "$#" -eq 1 ] && { [ "$1" = --help ] || [ "$1" = -h ]; }; then exit 0; fi
  exit 2
fi
uv run --locked python scripts/check-repo.py
uv run --locked python src/video_runners/tools/sync_config.py
# Keep tool versions aligned with .pre-commit-config.yaml.
uvx --from black==24.10.0 black --check .
uvx --from ruff==0.8.0 ruff check --config pyproject.toml .
uv run --locked pytest -q
