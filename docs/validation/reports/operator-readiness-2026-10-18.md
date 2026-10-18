# Operator readiness — October 18, 2026

This CPU-only follow-up adds preparation and payment-policy checks to existing
operator commands. Engine images, models, public IDs, runtime ownership modes
and the prod/dev Compose entry points remain unchanged. No GPU host, inference
job, funded signer or public application deployment was used in this work.

## Preparation checks

`prepare_weights.py --check` validates a saved receipt against its pinned asset
plan and recorded file inventory. Missing/stale receipts, mutable revisions,
changed extra-file revisions, deleted/truncated/empty weights, wrong offline
refs and paths escaping a volume fail. Preparation records files from the
downloaded snapshot, extra downloads and locally converted required assets.
Older receipts without an inventory require explicit repeat preparation; the
check itself never downloads or rewrites model data.

`init_deployment.py --check` captures resolved private Compose configuration and
inspects its selected managed profiles. It checks trusted policy, independent
admin/control settings, control-token agreement, the engine network, Docker API,
GPU UUID presence, host-RAM limits, staged service/engine images, external volumes
and asset inventories. Public priced-catalog filenames do not change profile
mapping. Unselected optional models need no assets. Literal shell dollars follow
the controller's variable-expansion rules without evaluating shell text or
substituting the client host's environment.

The checker uses a local Unix-socket daemon and readable volume data. It reports
missing resources without creating/pulling/building them. Captured Compose
configuration and command errors are not printed. GPU UUID presence is not proof
of container device access or free VRAM. A named runtime entry is not used as a
substitute for a real GPU test. Startup restoration, active controller operations,
GPU leasing, network reachability and inference remain separate runtime checks.

## Offline payment checks

`init_deployment.py --check-payments` compares explicit private TOML settings
with selected public catalog rates. It checks on-chain network/chain agreement,
uint256 face value/probability bounds, the pinned node's rejection of an
always-winning probability, positive finite rates/limits, deposit-multiplier
bounds, ticket EV and a proposed batch against signer ceilings.

Expected value uses exact `Fraction(face × probability, 2^256 - 1)`. JSON/TOML
decimal values are parsed without a float conversion. Regression examples catch
both a ticket EV limit and an hourly rate just beyond a ceiling that binary
floating-point rounding could hide. Results expose only selected monetary
values, rational EV, batch capacity and generic diagnostics. The CLI was tested
with nonexistent key paths and network access disabled by the test seam; only
the explicitly supplied TOML/catalog files were read.

This is a narrow offline policy comparison, not complete node configuration or
production-economic acceptance. It does not merge CLI/environment overrides,
choose tariffs, change SDK batching, enforce a cumulative budget, inspect account
funding or submit payments. See the canonical
[payment-setting procedure](../../guides/node-deployment.md#review-payment-settings-offline).

## vLLM startup investigation

The existing engine remains pinned to
`vllm/vllm-omni@sha256:5cba1538c6f8ee81e8bea6708c24e68d7b2640f466a9fbf2ef15e68f2168b48b`.
The earlier [GPU acceptance](operator-acceptance-2026-10-18.md#engine-startup-limitation)
captured a 30-second asynchronous warmup-output timeout in that image. Registry
configuration metadata identifies base vLLM build `ffd46bfab2128bb84146050e98b51a617c6575ab`
and base version `v0.26.0`; these labels do **not** establish the vLLM-Omni source
revision. Inspection fetched metadata only, not GPU image layers.

The candidate source is immutable upstream commit
[`a965251bf1a3db3ab6871307ec39c938c0634479`](https://github.com/vllm-project/vllm-omni/commit/a965251bf1a3db3ab6871307ec39c938c0634479).
Its [diffusion engine](https://github.com/vllm-project/vllm-omni/blob/a965251bf1a3db3ab6871307ec39c938c0634479/vllm_omni/diffusion/diffusion_engine.py)
uses `VLLM_OMNI_ASYNC_OUTPUT_TIMEOUT` with a 600-second default at the asynchronous
output wait. An isolated CPU execution of that function, extracted from the
pinned source without engine imports, observed:

| Setting              | Returned timeout |
| -------------------- | ---------------- |
| Unset                | 600 seconds      |
| `120`                | 120 seconds      |
| Invalid numeric text | 600 seconds      |
| `0`                  | 600 seconds      |

The [serve parser](https://github.com/vllm-project/vllm-omni/blob/a965251bf1a3db3ab6871307ec39c938c0634479/vllm_omni/entrypoints/cli/serve.py)
still declares the current CPU-offload and VAE-tiling flags; the Wan 2.2 pipeline
is present. These static checks do not prove model loading, engine HTTP API,
cancellation, output equivalence, memory use or startup reliability.

The captured installed engine uses a fixed 30-second constant. Merely adding the
new environment variable to that old image would not change its wait. Increasing
the runner/controller startup bound also does not alter the engine's internal
output wait. The candidate is therefore a lead for a later engine investigation,
not a promoted image or a verified startup fix. No engine source patch, image-pin
change, GPU-image build/publication or model download was performed.

## Verification and cleanup

Behavior tests were driven from observed failures before implementation. Extra
boundary/contract cases document existing passing behavior. Deliberately disabling
the recorded file-size comparison made the truncated-weight test fail; routing
the EV ceiling through float conversion made the precision test fail. Both
mutations were restored before the full checks.

A local CPU-only model-tools image checked intact fixture assets successfully
and rejected a deleted weight. Both runs used `runc`, no network, a read-only
container filesystem and read-only asset mounts. Fixture bytes and modification
times were unchanged. These were fixture bytes, not model weights or generated
videos. A real Compose/Docker negative check ran as a standalone standard-library
command, reported intentionally absent volumes, redacted private values and left
container/network/volume inventories unchanged.

Full repository checks passed: **302 tests**, Black, Ruff, configuration/reference
sync and repository links/import boundaries. The existing 34 aiohttp warnings
remain. All **37 Compose configurations** resolved. The packaged model-tools
script's SHA-256 matched the checked-out source before its read-only checks.

All owned test containers, temporary CPU image tags and fixture directories were
removed. Existing Docker resources and model/cache volumes were not modified.
Private source snapshots and test logs retain detailed CPU evidence locally.

## Remaining acceptance

Schedule a bounded GPU window before changing the engine pin: repeated starts,
graceful/forced switching, both SDK delivery modes, current output checks and
resource cleanup across all default engines. Agree on public node HTTPS,
production tariff, ticket economics and a total paid-test budget before public
or sustained paid acceptance. The [readiness plan](../../plans/active/operator-readiness.md)
keeps these gates separate from completed CPU preparation work.
