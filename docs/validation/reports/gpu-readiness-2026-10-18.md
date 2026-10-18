# Free GPU readiness — October 18, 2026

The operator approved a bounded free GPU follow-up after the
[CPU readiness work](operator-readiness-2026-10-18.md). Public/paid acceptance was
explicitly deferred because its node endpoint, tariff and spending cap are not
available. No signer, payment keys, funded requests or public deployment were used.

## Tested configuration

The source was `a36141a4180ed8c18bedbb23df7e4d80afed1b83`. Temporary CPU runner,
controller and model-tools images were built from its clean archive. Installed
runner package hashes matched the checkout. The existing upstream node stayed at
`08081dbda0f4f7b56e362e3af4b6965bfa1b73a4`. The test added an isolated offchain node
to the production provider Compose entry point through a private temporary overlay.
SDK requests and media used direct LAN HTTP; SSH was management only.

Hardware was one RTX 5090 with driver `580.178.04`. Existing engine images were
reused without pulling, building or publishing GPU images:

| Engine    | Observed image ID                                                         |
| --------- | ------------------------------------------------------------------------- |
| SGLang    | `sha256:b1259f3ea3275f66237c498ea388919729018bc9f01c3d638391e06e2cf3f469` |
| LightX2V  | `sha256:7d3fe67ce806e6736d84566c788b9073b2452d64293c10b5c88826c0e3d6f013` |
| vLLM-Omni | `sha256:5cba1538c6f8ee81e8bea6708c24e68d7b2640f466a9fbf2ef15e68f2168b48b` |

An initial setup error prevented the non-root node from reading its temporary
configuration/bootstrap mounts. Correct ownership and config permissions resolved
it before any video request. SGLang was already warming during that correction;
the resumed Compose wait is not a cold-start measurement.

## Saved-asset preflight

The new deployment check accepted the host/policy/images/volumes but rejected old
preparation receipts without inventories. Repeating normal preparation with
networking disabled and offline mode refreshed the three default receipts from
cached assets: 29 SGLang, 22 LightX2V and 29 vLLM inventory entries. No model was
downloaded. The complete managed preflight then passed for all three defaults;
unselected optional profiles needed no additional assets.

## SDK delivery

Each default model produced one single-shot clip and two clips in one persistent
session. All **nine MP4s** decoded fully at the requested dimensions/frame count.
The fixed prompt and seeds match the earlier acceptance procedure.

| Engine/default      | Workload                   | Single-shot request | Two-clip session |
| ------------------- | -------------------------- | ------------------- | ---------------- |
| SGLang FastWan 1.3B | 832×480, 61 frames, 16 FPS | 6.55 s              | 12.56 s          |
| LightX2V Wan 1.3B   | 832×480, 81 frames, 16 FPS | 68.46 s             | 107.85 s         |
| vLLM-Omni Wan 5B    | 832×480, 49 frames, 24 FPS | 31.51 s             | 50.82 s          |

Request times exclude engine loading. Every seed-42 single-shot SHA-256 matched
the [earlier verified output](operator-acceptance-2026-10-18.md#hardware-and-payment-acceptance).
This establishes delivery and deterministic reproduction for these inputs, not
improved visual quality. Inference peak-memory telemetry was not collected by
the client-host validator.

## Startup and recovery

The initial vLLM load and three additional starts after switching to LightX2V
passed. Their complete switch/readiness times were 52.13, 51.00, 52.95 and
47.21 seconds. They reused persistent model/compiler caches; these are not
clean-compilation measurements. The earlier 30-second output timeout did not
recur in this sample, which does not establish that the intermittent issue is fixed.

Each default engine also passed deliberate idle engine loss, automatic recovery
and one fresh decoded single-shot request. Fault injection used the controller's
durable container ID and checked trusted configuration, not label-only ownership.
The original container was absent after each recovery.

| Engine    | Recovery to idle registered readiness | Fresh clip |
| --------- | ------------------------------------- | ---------- |
| SGLang    | 62.76 s                               | 61 frames  |
| LightX2V  | 24.64 s                               | 81 frames  |
| vLLM-Omni | 59.81 s                               | 49 frames  |

Graceful switching during a LightX2V request delivered its complete 81-frame MP4
before SGLang became ready. The full switch took 126.30 seconds, including the
replacement load; the 120-second policy limits the active-work drain rather than
the subsequent model load.

A separate vLLM request used 200 steps and 81 frames. A normal switch returned
HTTP 409 after 120.33 seconds while the job remained active, with its engine and
registrations unchanged. Explicit force then cancelled that client, confirmed
the old engine was absent and made LightX2V ready; the complete check took
43.26 seconds. The cancelled request produced no completed MP4 and was not replayed.

LightX2V then generated a fresh 81-frame MP4. Shutdown during another LightX2V
generation cancelled its client and removed the owned engine in 10.43 seconds.
No completed video was reported for either explicitly cancelled request. GPU
memory returned to 2 MiB with no compute processes.

The complete window produced **14 fully decoded videos**: nine from the initial
two-mode matrix, three after engine-loss recovery, one drained before switching
and one after force. No generation with an unknown outcome was resubmitted.
Failed-start rollback was not repeated in this window; its earlier evidence
remains in the [acceptance report](operator-acceptance-2026-10-18.md#active-work-switching-and-shutdown).

## Cleanup

After verified engine deactivation, all four temporary services, owned networks,
the temporary controller-state volume, three temporary CPU images and the remote
staging directory were removed. Startup-log followers and the validation lease
holder exited. No owned test container/network or GPU compute process remained.

Configuration fingerprints of five unrelated containers and all 29 preexisting
volumes matched their baseline. All 163 recorded weight paths retained their
sizes and modification times; the offline inventory refresh is retained for
future checks. Existing engine images, model/compiler caches and the shared
lease volume remain. Wallet/key files were never opened or mounted. Private local
evidence retains clips, results, redacted service logs and fingerprints rather
than raw unrelated container configuration.

## Limits

Engine pins, launch recipes and model defaults are unchanged. The upstream timeout
candidate remains unpromoted; successful starts of the existing image cannot
establish that an intermittent failure is fixed. This window adds no public,
paid, sustained-load, multi-GPU, optional-model or visual-quality acceptance.
