# Operator readiness

Approved on October 18, 2026: CPU-only investigation, deployment preflight and
payment configuration work. Keep current models, engine pins, ownership modes,
app IDs and Compose entry points. GPU inference, engine replacement, public
deployment and paid spending require the separately scheduled acceptance window.

## Deliverables

- Compare the pinned vLLM warmup failure with an immutable upstream candidate;
  record compatibility checks and the remaining hardware gate.
- Extend existing preparation/initialization commands with explicit checks for
  saved assets, selected images, external volumes, GPU assignment and launch
  configuration. Checks must not download weights or launch GPU services.
- Document and validate node ticket parameters, advertised model rates and
  signer ceilings independently. Use exact arithmetic; choose no production
  tariff or spending budget on the operator's behalf.
- Keep diagnostics free of secrets and retain CPU/hardware/payment evidence
  boundaries. Update canonical guides and the validation matrix.

## Behavior list

- [x] Asset checks reject missing/stale/incomplete receipts and missing files.
- [x] Preparation records the selected file inventory and pinned plan identity.
- [x] Asset checks preserve file contents and need no download dependencies.
- [x] Deployment checks resolve existing Compose/env selections without printing secrets.
- [x] Missing images/volumes, wrong GPUs and invalid trusted policies fail with corrective guidance.
- [x] Requested profiles are explicit; unselected optional profiles are not required.
- [x] Payment checks use exact ticket EV arithmetic and enforce signer ceilings.
- [x] Invalid/non-finite monetary settings fail without opening keys or contacting RPC.
- [x] Current and candidate vLLM code differences have immutable source evidence.
- [x] Full CPU, formatting, documentation and Compose checks pass.

## CPU evidence

The [dated report](../../validation/reports/operator-readiness-2026-10-18.md)
records 302 CPU tests, 37 Compose configurations, two rejected precision/inventory
mutations, real CPU container checks with read-only mounts and networking disabled,
an actual non-mutating Compose/Docker negative check, and verified cleanup.
The canonical [deployment guide](../../guides/container-deployment.md#check-preparation-before-startup)
and [payment guide](../../guides/node-deployment.md#review-payment-settings-offline)
own the reusable commands and their limits.

## Hardware gate

During a later agreed window, measure repeated starts and switching, both paid
delivery modes, bounded sustained operation and final settlement. Review the
node HTTPS URL, tariff, ticket economics and total test budget first. Preserve
external data and clean owned resources after the run. CPU checks do not promote
an untested engine image or establish production readiness.

## Free GPU follow-up

The operator subsequently approved the free GPU window and explicitly deferred
public/paid acceptance while its endpoint, tariff and budget are unavailable.
The [hardware report](../../validation/reports/gpu-readiness-2026-10-18.md) records
the current source and existing engine pins, offline receipt refresh, both SDK
modes, four controlled vLLM starts, recovery/fresh generation for all three
defaults, active drain/refusal/force/shutdown and 14 decoded videos. Owned-resource
cleanup is verified; saved models/caches and unrelated workloads are preserved.
The cached-start sample did not reproduce the intermittent vLLM timeout and does
not resolve that risk or validate the upstream candidate.
