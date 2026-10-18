# Operator release, monitoring and bounded switching

Scope approved on 2026-10-17: stop GPU trials and clean owned resources; implement
versioned container release tooling, private production metrics, and bounded
model switching. Preserve all models, IDs, ownership modes, delivery routes and
external data. The broader provider-platform rewrite stays deferred.

## Decisions

- Registry hostname/namespace/authentication are private operator settings. Reuse
  the existing Docker login locally; use separately scoped GitHub secrets in CI.
- Publish distinct CPU runner/controller/node/model-tools images. Operators pull
  upstream SGLang/vLLM-Omni and locally prepare the existing LightX2V image, then
  download model weights into external volumes. CPU publication/pulling performs
  no GPU engine action and requires no engine baseline.
- Source/version tags plus digest-only CPU deployment manifests, with no `latest`.
  Reuse existing prod/dev Compose entry points and preserve the operator's separate
  `.engine-images.env`. The earlier unreleased combined-bundle format is rejected.
- Normal CPU CI uses a GitHub-hosted worker. Node reuse from a complete prior CPU
  manifest is optional and requires matching source, Dockerfile and platform.
  A first CPU release builds four CPU roles without any previous manifest. No
  self-hosted worker service or GPU engine publication is needed.
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
- [x] Shutdown cancels pending admin switches and refuses new switches before final deactivation.
- [x] Release roles/inputs are pinned and credentials/mutable refs are refused.
- [x] Publishing records registry digests and exports reusable Compose inputs.
- [x] Incomplete manifests cannot be pulled/deployed.
- [x] CPU-only publication and pulls require no engine baseline and preserve operator engine settings.
- [x] Optional node reuse retains provenance; incompatible/legacy GPU bundles are refused before Docker actions.
- [x] Full CPU/format/package/Compose checks and real managed/bundled fixture verification.
- [x] Clean-source managed CPU rerun passed after heavy extraction ended; the earlier failed receipt is retained.
- [x] Local source checkpoint, four-role CPU registry publication and actual digest-based pull/CLI verification.

The [release guide](../../guides/container-releases.md),
[monitoring guide](../../guides/monitoring.md) and canonical
[switching procedure](../../guides/container-deployment.md#generate-inspect-and-switch)
own operating instructions. The [dated report](../../validation/reports/operator-release-2026-10-17.md)
records 249 CPU tests, 37 Compose configurations, fresh wheel installation,
16 decoded fixture clips, verified cleanup and CPU-only registry digest/CLI evidence.

## Acceptance follow-up — 2026-10-18

The operator explicitly resumed completion work, including GitHub publication
and credentials, GPU lifecycle checks and production acceptance. This extends
the earlier CPU-only implementation scope; quality and longer-duration
experiments remain paused. Preserve protected keys, wallet/model/cache volumes
and unrelated workloads; remove owned acceptance deployments afterwards.

- [x] Reproduce cleanup shutdown/late-arrival failures and add regression coverage.
- [x] Honor runner stop grace, recapture durable ownership and retain unresolved state.
- [x] Pass full CPU and Compose checks and an actual managed Docker run.
- [x] Push cleanup changes and configure private GitHub registry settings.
- [x] Run the hosted four-role CPU release and normal GitHub CI successfully.
- [x] Verify all three default engines through SDK delivery on the reserved GPU.
- [x] Record real active-job drain, timeout, force, rollback and shutdown outcomes.
- [x] Verify replacement-node paid single-shot and two-clip persistent delivery for all three defaults.
- [x] Verify canonical finalized winning-ticket settlement: 12 confirmed redemptions, zero unsettled tickets.
- [ ] Confirm production HTTPS/pricing and a bounded sustained-operation check.
- [x] Recheck the canceled engine tag is absent; resume no engine publication.
- [ ] Inspect optional registry housekeeping with verified server-administrator access.
- [x] Clean owned deployments and synchronize the final evidence/debt matrix.

The [acceptance report](../../validation/reports/operator-acceptance-2026-10-18.md)
records observed results and separates completed checks from external inputs.
