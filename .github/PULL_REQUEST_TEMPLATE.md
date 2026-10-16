## What and why

<!-- What does this change, and what problem does it solve? Link issues. -->

## How it was tested

- [ ] `scripts/check.sh` (repository links/boundaries, Black, Ruff and CPU tests)
- [ ] Relevant [verification tiers](../docs/reference/checks.md) identified below
- [ ] `tests/e2e/managed.sh` or the affected isolated Docker harness
- [ ] On a GPU (engine, model, GPU, driver, timings below), or not applicable

<!-- For engine or catalog changes, paste the GPU, driver, image tag, model,
resolution/frames/steps, load time and seconds per clip. -->

## Checklist

- [ ] README, CHANGELOG (`Unreleased`) and `.env.example` updated where behavior or configuration changed
- [ ] No secrets, tokens or model weights committed
- [ ] Docs and shared evidence omit operator hostnames, actual addresses, account identities and private resource names
- [ ] App ids, endpoints and event shapes unchanged, or the change is called out as breaking
