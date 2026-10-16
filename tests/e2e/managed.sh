#!/usr/bin/env bash
# Stable entry point for an isolated managed CPU Docker run.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
exec uv run --locked python src/video_runners/tools/cpu_harness.py --mode managed --engine "${TEST_ENGINE:-stub}" "$@"
