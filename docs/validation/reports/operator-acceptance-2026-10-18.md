# Operator acceptance follow-up — 2026-10-18

This record covers cleanup reliability, hosted CPU publication and resumed
hardware/payment acceptance. It does not change engine ownership, ship GPU
engines, promote models or resume quality/duration experiments. Host identifiers,
addresses, registry settings and account identities remain in private evidence.

## Cleanup reliability

Regression tests first reproduced premature runner termination, state removal
before detection of late containers, unresolved controller operations, and a
durably owned engine completing during runner shutdown. Each failed for its
intended reason before implementation. Existing ownership regressions remain
unchanged. Repeated cleanup also retains an unresolved controller marker when
the controller has subsequently been stopped manually.

Runner teardown allows at least 150 seconds or a longer configured stop grace.
Ownership is recaptured while the controller remains readable. Pending or
unsuccessful latest operations retain recovery resources. Late-container checks
precede infrastructure removal. No unrecorded engine is adopted by label, and no
daemon prune is used. See the [validation-run guide](../../guides/validation-runs.md).

Full checks passed with **259 CPU tests** and **37 Compose configurations**.
An initial clean-source managed Docker run decoded 12 fixture videos. After the
delivery-drain correction, another managed run decoded 10, including a live SDK
response drained before switching. That latter local receipt records dirty docs;
the clean-source [normal CI run](https://github.com/Cloud-SPE/livepeer-video-engine-runners/actions/runs/39138960275)
also passed the managed/bundled matrix. Both local runs completed verified cleanup.
These fixtures do not establish GPU or payment readiness.

## Hosted CPU release

Runtime source **`6c613849d080c6d1218f7f5edcd587aea473b513`** was pushed. Both
normal CI and the [hosted release](https://github.com/Cloud-SPE/livepeer-video-engine-runners/actions/runs/39140608905)
passed. An earlier release of cleanup source `c998ea6` also passed. Two intervening
release attempts failed at registry login during a connection outage; they did
not publish their newer source. After connectivity recovered, the latest release
completed. Registry settings use repository variables and separately stored secrets.
The workflow publishes only runner, controller, model-tools and node; compatible
node reuse retained its previous digest and upstream provenance. No GPU engine
was built, pulled, pushed or run by publication. The manifest and env artifact
were downloaded. All four latest CPU digests were pulled locally and their
entrypoints passed `--help` with network disabled and the CPU runtime. The GPU
tests used a separately built CPU runner from a clean checkout of the same
runtime revision; installed runner module hashes matched source. The unchanged
controller used the earlier published CPU image. The node remained the unmodified
pinned upstream revision `08081dbda0f4f7b56e362e3af4b6965bfa1b73a4`.

## Hardware and payment acceptance

Acceptance uses existing engine images and saved model/cache volumes in offline
mode, one managed instance on a reserved RTX 5090, and a separate local Python
SDK client. Management uses SSH; application/media requests use direct LAN HTTP.
No SSH forwarding or legacy go-livepeer deployment is used.

All three default models passed one single-shot SSE request and one persistent
session with two clips, using the Python SDK and no signer for this initial free
check. All nine MP4s decoded fully. Each seed-42 single-shot reproduced the
previous verified SHA-256; this checks delivery/reproducibility, not visual quality.

| Engine / default    | Dimensions | Frames / fps | Seed-42 single-shot SHA-256                                        |
| ------------------- | ---------- | ------------ | ------------------------------------------------------------------ |
| SGLang FastWan 1.3B | 832×480    | 61 / 16      | `a9a7b0b263042579627c4dca231f56e82527175ae1093fb8c8f6dafbed39f3f8` |
| LightX2V Wan 1.3B   | 832×480    | 81 / 16      | `7e87e3d74b765ea851f55efc97329f701a04836b946e146a2e1e56cd5998bb21` |
| vLLM-Omni Wan 5B    | 832×480    | 49 / 24      | `fda2870b5f6a150bb998344d7929c253c8bf09c468d40db4aa21ca598ccfd44a` |

### Active-work switching and shutdown

| Check                                      | Observed result                                                                                                                                        |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Graceful switch during LightX2V generation | Complete 81-frame MP4 arrived before switching to SGLang; total management request 121.51 seconds includes the separate model load                     |
| 120-second drain deadline                  | A vLLM request with 200 steps and 81 frames remained active; HTTP 409 returned after 120.37 seconds, with engine and registration identities unchanged |
| Explicit force after refusal               | Client cancelled, old engine absent and replacement LightX2V ready; complete management/check sequence 44.31 seconds                                   |
| Fresh work after force                     | LightX2V produced a fully decoded 81-frame MP4                                                                                                         |
| Failed replacement startup                 | A test-only `/bin/false` profile returned HTTP 500; previous SGLang engine and both registrations restored in 59.80 seconds                            |
| Fresh work after rollback                  | SGLang produced a fully decoded 61-frame MP4                                                                                                           |
| Shutdown during LightX2V generation        | Client cancelled, owned engine absent and no compute process; GPU memory returned to 2 MiB in 9.95 seconds                                             |

These are observed cases on one GPU, not timing guarantees or coverage of every
failure point. No generation with an unknown outcome was automatically retried.
An unsuitable FastWan deadline workload finished too quickly. A 500-step vLLM
request was rejected by its 200-step validation limit before a job was created;
the subsequent deadline case used different inputs and its own output record.

The tests exposed two runner defects. First, a fixed five-second rollback wait
could expire before the controller finished restoring the previous engine. It
now uses that previous profile's startup bound plus 90 seconds. Second, releasing
the GPU lock at inference completion could unregister a single-shot runner while
the node still delivered its response. Sending the final SSE EOF was necessary
but insufficient across the LAN. Graceful drain now also waits for the node's
single-shot delivery-session release within the existing drain deadline. New
regressions cover restoration, delayed delivery and refusal/admission on timeout;
the real CPU SDK integration exercises switching during delivery.

### Engine startup limitation

vLLM intermittently failed before accepting jobs, although later explicit starts
and the recorded generations passed. Captured engine logs show an asynchronous
warmup output wait timing out (`_ASYNC_OUTPUT_TIMEOUT = 30.0`) in the pinned
vLLM-Omni engine. This is not evidence of an OOM. No engine patch, unsupported
execution flag or automatic generation replay was used to obtain a pass. Startup
reliability remains tracked separately in [technical debt](../../plans/tech-debt.md).

### Paid delivery and settlement

The same three defaults passed paid single-shot and two-clip persistent delivery
through a local node signer: **nine more fully decoded MP4s**, all at the default
dimensions/frame counts above. The seed-42 outputs matched the free checks.
The public catalog advertised a **$1/hour test rate**, with a **$2/hour signer
ceiling**. These are rates, not cumulative budgets or a production tariff.

| Engine    | Single-shot request | Two-clip persistent session | Successful payment-signing responses | HTTP 402 challenges |
| --------- | ------------------- | --------------------------- | ------------------------------------ | ------------------- |
| SGLang    | 9.94 s              | 15.00 s                     | 4                                    | 2                   |
| LightX2V  | 70.99 s             | 111.07 s                    | 14                                   | 2                   |
| vLLM-Omni | 34.07 s             | 52.90 s                     | 8                                    | 2                   |

Request times include payment/discovery setup and delivery, not model loading.
Persistent times cover both clips in the session. A temporary client observer
returned the original SDK HTTP response unchanged and recorded only method,
endpoint category and status; it recorded no URLs, headers, bodies, signatures
or payment credentials. The **26 successful signing responses** and **six 402
challenges** prove payment-path execution, not 26 tickets or final cost.

The node durably stored **12 winning tickets**, each with face value
4,000,000,000,000 wei. All 12 mined receipts contain the expected
`WinningTicketRedeemed` event with matching payer, recipient and face value;
those identities and transaction hashes stay in private evidence.
At **16:04 UTC on October 18**, all 12 receipts were successful, canonical and
at or below the RPC's finalized head. The node recorded **12 confirmed
redemptions, 12 redeemed tickets and zero unsettled tickets**. This establishes
winning-ticket redemption and finalized settlement for this test path.
No funding, approval, account registration or
service-URI transaction was performed. The existing protected wallets/keys
were reused through read-only mounts and private staged secret files.

Receipt gas used multiplied by effective gas price totals **45,553,198,600,000
wei**, against **48,000,000,000,000 wei** of redeemed face value. These deliberately
small test tickets spent approximately 94.9% of gross face value on transaction
fees. This verifies a payment mechanism, not production pricing or profitability;
GPU and operating costs are not included.

Public production HTTPS, the production price and registry administration
require operator settings. Active acceptance resources are removed only after
owned engine shutdown and payment-state review.

## Cleanup and remaining acceptance

After paid delivery, the runner, controller, socket proxy, owned engine and
temporary controller-state volume were removed. No compute process remained;
GPU memory was 2 MiB. The local signer was removed. After finalized settlement,
the CPU payment node, remaining owned networks and private local/remote staging
directories were removed, including staged secret copies and temporary payment
state. Final inventory found **zero owned containers, networks or temporary
volumes**, and no GPU compute processes. Five unrelated containers retained
their recorded configurations and all **29 existing volumes** were retained.
Original payer/orchestrator key and password bytes, permissions and ownership
matched their pre-test snapshots.

The temporary build worktree was removed, along with disposable CPU runner tags
on both Docker hosts. Published CPU images, prepared engines and external wallet/model/cache/
lease volumes remain available for reuse. Private receipts, logs and test clips
remain locally for review; no service or staged credential directory remains.

The canceled earlier LightX2V publication still has no published manifest.
Registry-side orphan-upload/blob reclamation was not attempted: ordinary image
login is insufficient access to inspect the registry's backing storage and
garbage-collection configuration. No engine publication was resumed.

Public node HTTPS, production tariff acceptance and sustained public operation
are separate from the recorded private-LAN test. Existing application and object
storage HTTPS services do not establish an HTTPS endpoint for the Livepeer node.
The tests cover one GPU and serial model switching, not multi-GPU operation,
sustained load or every failure point. Quality work remains paused.
