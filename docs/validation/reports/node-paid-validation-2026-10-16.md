# Node signer paid GPU verification — 2026-10-16

All three default engines generated verified videos through the Python SDK,
a local **livepeer/node signer** and a **livepeer/node orchestrator on the RTX
5090 host**, using direct private LAN HTTP. No SSH tunnel, go-livepeer process
or traditional gateway daemon participated.

This verifies **paid single-shot SSE generation** for the listed configurations.
It does not establish paid persistent-session delivery, winning-ticket
redemption, final settlement or general production readiness.

## Deployment and inputs

- Test GPU: RTX 5090 with 32,607 MiB VRAM and NVIDIA driver 580.178.04.
  The client/signer ran on a separate Linux machine. Hostnames, addresses,
  account identities and private resource names are omitted.
- Both node roles used the same unmodified upstream source at
  [08081dbda0f4f7b56e362e3af4b6965bfa1b73a4](https://github.com/livepeer/node/tree/08081dbda0f4f7b56e362e3af4b6965bfa1b73a4).
  The orchestrator and signer are separate roles, not two orchestrators.
- Python SDK: the repository's locked `livepeer-gateway==1.0.0`, invoked by
  `video-client` through `validate_gpu.py`. No SDK or node fork was introduced.
- Source: the local worktree based on `9f57ee6`, including the focused cleanup.
  It was uncommitted, not a published release. The transferred 79-file public
  source archive had SHA-256
  `88924f23f4e5391cb29b37cdb7bd94e059015271e62be2bbb925860df7a96ed6`.
- Provider: canonical `compose.prod.yml` plus the explicit ingress overlay and
  private test image/config overrides. One runner/controller/active engine on
  the reserved GPU; the controller uses the restricted socket proxy.
- A separate, temporary node project used the existing orchestrator identity
  and redemption account. Its mainnet active status and gas balance were
  checked read-only before startup. The existing wallet volume was not modified.
- The local signer mounted the existing payer keystore read-only. Locked payer
  deposit and reserve, chain access and exchange-rate readiness were checked.
  No account creation, funding, token approval, registration or service-URI
  update was performed.
- The operator-owned test public catalog quoted **$1/hour**. The local signer
  ceiling was **$2/hour**; that is a rate ceiling, not a cumulative spending cap.
- SGLang and vLLM-Omni used the immutable images in
  [engine-images.json](../../../configs/engine-images.json). LightX2V used the
  previously prepared image
  `sha256:ad77b557477f36bb1d2248f925b0f9cd428bb2ca012dd76790895c8b3f2a6af1`.
- Saved weight receipts for all three defaults reported ready. Engines reused
  external model/cache volumes in offline mode; no model preparation/download
  command was run. The final owned engine's image, mounts, GPU request and
  labels passed the controller policy's identity verification.

The node advertised a client-reachable private LAN URL. Runner
registration/callback traffic used its private Docker network. The runner had a
reserved address on an existing private network, with a matching node grant. Admin stayed
on host loopback. Signer API and metrics stayed on client-host loopback.
SSH was used only for deployment, management and cleanup, never as a media or
SDK transport.

## Generation results

Each successful call used seed 42, the validation helper's standard fox prompt
and the catalog workload. Every frame decoded, dimensions/frame counts matched,
and all frames were distinct. Previews were shown during the run.

| Engine    | Output                     | Request time | MP4 bytes | Successful signer payment requests |
| --------- | -------------------------- | ------------ | --------- | ---------------------------------- |
| sglang    | 832×480, 61 frames, 16 fps | 7.59 s       | 404,855   | 2                                  |
| lightx2v  | 832×480, 81 frames, 16 fps | 70.57 s      | 283,382   | 18                                 |
| vllm-omni | 832×480, 49 frames, 24 fps | 32.87 s      | 622,150   | 9                                  |

Request time includes client startup, discovery/payment setup, inference and
delivery after model loading. These different models and workloads are
functional checks, not comparative engine benchmarks. This client-side run did
not sample remote GPU/cgroup peak memory.

| Engine    | MP4 SHA-256                                                        |
| --------- | ------------------------------------------------------------------ |
| sglang    | `a9a7b0b263042579627c4dca231f56e82527175ae1093fb8c8f6dafbed39f3f8` |
| lightx2v  | `7e87e3d74b765ea851f55efc97329f701a04836b946e146a2e1e56cd5998bb21` |
| vllm-omni | `fda2870b5f6a150bb998344d7929c253c8bf09c468d40db4aa21ca598ccfd44a` |

All three outputs matched their corresponding fixed-seed hashes from the earlier
[legacy compatibility trial](paid-validation-2026-10-15.md). This is observed
consistency for these pinned inputs, not a guarantee across arbitrary restarts,
versions or hardware.

Selecting LightX2V after SGLang took **29.59 s**; selecting vLLM-Omni afterward
took **52.15 s**. Each switch was an explicit authenticated management action
after the previous job finished. No generation request triggered model switching.

Each engine produced a successful validation receipt. Worktree-derived receipt
identifiers are omitted from this public summary; raw receipts were removed
after verification.

## Payment evidence

Temporary status-only HTTP instrumentation observed, for each successful job:

1. Discovery through the local signer returned the active model at a positive
   time-based price.
2. The remote node returned **HTTP 402** for the work request.
3. The local signer returned **HTTP 200** from `/generate-live-payment`.
4. The authenticated work request returned **HTTP 200** and delivered the video.
5. Subsequent signer payment requests and node session-payment renewals returned
   **HTTP 200** while generation continued.

Across the three jobs, there were **29 successful signer payment requests**
(2 SGLang, 18 LightX2V, 9 vLLM-Omni), plus the initial orchestrator-info signing
calls. These are HTTP response counts, not a ticket count, final cost or
settlement receipt. Instrumentation recorded no request/response bodies,
authorization headers, signatures or payment credentials. The SDK performed the
actual discovery, signing integration, payment refresh and streaming.

Before teardown, the runner was idle with no open sessions or recovery flag.
The node database held **zero winning tickets and zero redemption attempts**.
There was no pending redemption state to preserve, and this run does not verify
winning-ticket redemption or final settlement.

## Deployment findings

- Both existing legacy password files had trailing line endings. The node reads
  exact password bytes, so startup initially failed decryption. Private,
  owner-only test copies supplied the actual password without those line
  endings. Original key/password contents, ownership and permissions were
  checked before and after and remained unchanged.
- The local Docker daemon was rootless: host-owned key mounts appeared as
  container UID/GID `0:0`. The signer used that mapped identity with read-only
  mounts; protected key permissions were not changed.
- An initial SDK request returned HTTP 502 because the node could not resolve
  the runner's Docker alias. Direct HTTP to its reserved IP succeeded. The
  runner was idle and the failed request never reached the engine; no generation
  was replayed. Changing only the private advertised runner URL to the reserved
  literal IP and redeploying the runner fixed forwarding.
- Current signer examples and node/deployment guides now prefer direct LAN
  addressing and explain mapped file ownership, exact-byte private password
  copies and literal runner IPs. No runner, controller, adapter, SDK or node
  protocol implementation changed for this verification.

## Cleanup

After verification, owned test resources were removed from both machines:

- Runner, controller, engine, socket proxy, remote node and local signer.
- Provider-created networks, temporary controller/GPU-lease volumes and uniquely
  tagged test images. The pre-existing private network and unrelated workloads
  remained intact.
- Deployment copies, private env/config/password copies, source archive and
  downloaded source, payment/signer state, MP4s, previews, raw traces/logs and
  receipts. No tunnel or recurring service was installed.
- Existing wallet data, saved model/cache volumes and host/payer keys were
  preserved. GPU use returned to its idle baseline and unrelated workloads
  remained running.

Only this report's measurements/hashes and the conversation previews remain;
there is no retained test deployment or video-file download. Normal build and
dependency caches were preserved; Docker was not pruned.

## Remaining checks

Paid persistent-session delivery with the node signer, public HTTPS, full
network-wide discovery/selection, long-duration load, multi-GPU operation and
winning-ticket redemption/final settlement remain separate validation scopes.
See the [validation matrix](../index.md) and
[current deployment guide](../../guides/container-deployment.md).
