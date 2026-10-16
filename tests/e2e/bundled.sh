#!/usr/bin/env bash
# Isolated bundled CPU Docker run; no GPU or funded signer.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
exec uv run --locked python src/video_runners/tools/cpu_harness.py --mode bundled --engine stub "$@"
