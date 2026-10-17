# Operator release, monitoring and bounded switching

Scope approved on 2026-10-17: stop GPU trials and clean owned resources; implement
versioned container release tooling, private production metrics, and bounded
model switching. Preserve all models, IDs, ownership modes, delivery routes and
external data. The broader provider-platform rewrite stays deferred.

## Decisions

- Registry hostname/namespace/authentication are private operator settings. Reuse
  the existing Docker login locally; use separately scoped GitHub secrets in CI.
- Distinct CPU runner/controller/node/model-tools images plus a separate
  LightX2V engine image. Record pinned upstream SGLang/vLLM images and model inputs.
  Never bake weights into CPU images or merge node/runner roles.
- Source/version tags plus digest-only deployment manifests, with no `latest`.
  Reuse the same prod/dev Compose entry points; retain local build defaults.
- Metrics use the existing authenticated admin listener, not public generation.
  Do not deploy another monitoring stack or change host exporters.
- Graceful switching waits up to 120 seconds for active work. Expiry refuses the
  switch and leaves the job/registration intact. The positive finite timeout is
  configurable. Explicit `force: true` permits cancellation, but replacement
  requires confirmed owned-engine stop and completed task cleanup.
- Owned-engine stop and active-task cleanup have their own 120-second bound. Unknown outcomes fail closed;
  no automatic generation retry. Engine startup/rollback retain profile bounds.
- No new GPU, paid or duration work. CPU checks do not establish hardware readiness.
- No Git push, CI worker service installation or GitHub credential change follows
  automatically from local implementation/publication. Those are separate actions.

## Behavioral verification list

- [x] Private metrics refuse missing/wrong admin credentials and are absent publicly.
- [x] Actual single-shot/persistent outcomes, duration, refusals and recovery are counted.
- [x] Graceful drain timeout leaves active work/registration unchanged.
- [x] Explicit force cancels work, confirms engine stop before activation and blocks admission.
- [x] Stop error/timeout fails closed; deliberate skipped-stop mutation is rejected.
- [x] A persistent task cancelled before its first instruction releases its GPU reservation.
- [x] Admin force flags require JSON booleans; concurrent/external-mode restrictions remain.
- [x] Release roles/inputs are pinned and credentials/mutable refs are refused.
- [x] Publishing records registry digests and exports reusable Compose inputs.
- [x] Incomplete manifests cannot be pulled/deployed.
- [x] Full CPU/format/package/Compose checks and real managed/bundled fixture verification.
- [ ] Local source checkpoint, registry publication and digest-based pull/CLI verification.

The [release guide](../../guides/container-releases.md),
[monitoring guide](../../guides/monitoring.md) and canonical
[switching procedure](../../guides/container-deployment.md#generate-inspect-and-switch)
own operating instructions. The [dated report](../../validation/reports/operator-release-2026-10-17.md)
records 235 CPU tests, 37 Compose configurations, fresh wheel installation,
16 decoded fixture clips, cleanup and the remaining publication boundary.
