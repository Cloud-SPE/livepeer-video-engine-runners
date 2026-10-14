## What and why

<!-- What does this change, and what problem does it solve? Link issues. -->

## How it was tested

- [ ] `uv run pytest`
- [ ] `scripts/e2e.sh` against `ENGINE=stub docker compose up -d --build --wait`
- [ ] On a GPU (engine, model, GPU, driver, timings below), or not applicable

<!-- For engine or catalog changes, paste the GPU, driver, image tag, model,
resolution/frames/steps, load time and seconds per clip. -->

## Checklist

- [ ] README, CHANGELOG (`Unreleased`) and `.env.example` updated where behavior or configuration changed
- [ ] No secrets, tokens or model weights committed
- [ ] App ids, endpoints and event shapes unchanged, or the change is called out as breaking
