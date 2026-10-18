# Production and development deployment

The two everyday entry points use the existing managed lifecycle: a CPU runner,
CPU controller and private socket proxy control a separate engine container.
Bundled child-process and external operator-owned modes remain available below.
Both single-shot and persistent-session delivery remain supported.

| Entry point                                | Purpose                                              | Starts an orchestrator? |
| ------------------------------------------ | ---------------------------------------------------- | ----------------------- |
| [compose.prod.yml](../../compose.prod.yml) | Provider connected to an existing node               | No                      |
| [compose.dev.yml](../../compose.dev.yml)   | Complete free development stack, CPU stub by default | Yes, one pinned node    |

Run commands from the repository root. Requires Python 3.12+, Docker Compose
**2.24.4 or newer**, and Docker API v1.51 for managed operation. Real engines also
require a compatible NVIDIA driver and Container Toolkit. Routine Python checks
need none of those external resources; see [verification tiers](../reference/checks.md).

All hostnames, paths and addresses in deployment examples are placeholders.
`192.0.2.10` and `192.0.2.20` are documentation-only addresses: replace them
with the actual private LAN/VPN addresses reachable by the indicated component.
Docker subnet examples must also be replaced to match the selected network.

## Image names and roles

These are the default image references in Compose and preparation tooling:

| Component                        | Image reference                                  | Purpose                                                                           |
| -------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------- |
| Orchestrator and optional signer | `livepeer-node:local`                            | Same pinned upstream node build, started with `orchestrator` or `signer`          |
| Runner                           | `livepeer-video-runner:local`                    | CPU adapter and Livepeer integration                                              |
| Controller                       | `livepeer-video-controller:local`                | CPU engine lifecycle and Docker policy                                            |
| Socket proxy                     | `ghcr.io/tecnativa/docker-socket-proxy@sha256:…` | Restricted Docker API; full pin is in the root Compose files                      |
| SGLang engine                    | `lmsysorg/sglang@sha256:…`                       | Upstream GPU image pinned in `configs/engine-images.json`                         |
| vLLM-Omni engine                 | `vllm/vllm-omni@sha256:…`                        | Upstream GPU image pinned in `configs/engine-images.json`                         |
| LightX2V engine                  | `livepeer-video-lightx2v-engine:local`           | Locally prepared GPU image; managed policy uses its immutable `sha256:…` image ID |
| CPU test engine                  | `livepeer-video-stub-engine:local`               | Development fixture, built by the `engine-image` service                          |
| Model preparation                | `livepeer-video-model-tools:local`               | One-shot weight preparation; not a running provider service                       |

The preparation image downloads weights; `prepare_engines.py` stages GPU images
on the host. The runner and controller share Python package layers, with separate
entrypoints. They contain neither the node binary nor GPU engine dependencies.
The full image reference, including its tag or digest, identifies the image.
`:local` denotes a local build, not a published registry release. Test harnesses
use isolated run-specific image tags; those are not deployment defaults.

For versioned registry images, use the [release workflow](container-releases.md).
The same Compose files accept digest overrides for runner, controller, node and
model preparation images; local build defaults remain available. CPU releases
leave engine preparation and `.engine-images.env` under operator control.

Advanced bundled mode uses `livepeer-video-engine-runners-<engine>:local` and
deliberately includes the runner and engine together. It is a separate recipe
from the default managed stacks.

## Complete development stack

```sh
uv sync --locked
mkdir -p "$HOME/.config/livepeer-video"
VIDEO_ENV="$HOME/.config/livepeer-video/dev.env"
python3 src/video_runners/tools/init_deployment.py --engine stub \
  --project video-dev --env-file "$VIDEO_ENV"
docker compose --env-file "$VIDEO_ENV" -f compose.dev.yml up -d --build --wait
uv run video-client --list
uv run video-client --output fox
uv run video-client --mode persistent --clips 2 --output fox-session
```

Initialization creates random independent tokens, available subnet/port settings
and external volumes. It refuses to overwrite an existing env file. The first
build compiles pinned `livepeer/node` source. The one-shot `engine-image` service
builds the CPU stub and exits before the controller starts; the controller then
launches the actual engine from that image. Default development needs no GPU,
wallet or model downloads. [`.env.example`](../../.env.example) documents settings;
initialization is preferred over manually copying credentials and network defaults.

The client defaults to port 8935. If initialization selected another
`ORCHESTRATOR_PORT`, pass `--discovery http://127.0.0.1:PORT/discovery`. Similarly,
use the generated `RUNNER_ADMIN_PORT` for management. Settings do not automatically
become environment variables in the shell running the client.

To develop against real GPUs, initialize another env with `--engine all` or an
individual engine and `--gpu GPU-UUID` if needed. Prepare images and weights below,
then start `compose.dev.yml` with both that env file and `.engine-images.env`.
The same stack keeps its free local orchestrator. No runtime mode is retired.

For optional paid development, start the existing signer recipe on the client
machine and pass its URL to the Python client; see the [node guide](node-deployment.md).
Keys and signer configuration are explicit, separate prerequisites. The free
stack does not require them or automatically submit a paid request.

## First production deployment on a Linux GPU host

Run provider initialization, image staging, weight preparation and Compose on the
Docker host that owns the assigned GPU. Run Python client and optional signer
commands on the client machine. The existing node can share the provider host
or run elsewhere; configure URLs reachable in both directions.

Install Docker and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
configure the toolkit for the deployment daemon, and verify `nvidia-smi`,
`nvidia-smi --query-gpu=uuid,name --format=csv,noheader` and `docker compose version`.
Engine CUDA and the host driver must be compatible. Rootless Docker must use its
configured toolkit and actual socket, not a guessed rootful daemon.
The recorded hardware checks use an RTX 5090; other GPUs need their own model,
driver and memory validation. These commands do not assume a specific server.

```sh
mkdir -p "$HOME/.config/livepeer-video"
VIDEO_ENV="$HOME/.config/livepeer-video/prod.env"
python3 src/video_runners/tools/init_deployment.py --engine all \
  --project video-engines --existing-orchestrator --env-file "$VIDEO_ENV"
# On a multi-GPU server, add --gpu GPU-your-reserved-uuid.
# Edit the generated private file: orchestrator URLs, secret and private bind IP.
python3 src/video_runners/tools/prepare_engines.py all
for engine in sglang vllm-omni lightx2v; do
  docker compose --project-directory . --env-file "$VIDEO_ENV" \
    -f deploy/compose/assets.yml run --rm --build model-tools "$engine"
done
docker compose --env-file "$VIDEO_ENV" --env-file .engine-images.env \
  -f compose.prod.yml up -d --build --wait --wait-timeout 3600
```

Prepare on the deployment Docker daemon. Read the generated settings before
starting. [The production env example](../../deploy/templates/prod.env.example)
shows the connection fields. Production requires explicit bootstrap/admin/control
credentials and both URLs. Its generation port binds to `RUNNER_BIND_HOST`
(loopback unless set); restrict that private interface to your orchestrator.
The production file starts no demo node, signer or stub-image build service.
Catalog/image validation fails before a missing or untrusted profile can launch.

An existing deployment keeps its exact project name, namespace, engine network,
GPU and external volume names. Initialize new settings only for a new deployment;
do not overwrite private operator files or silently adopt unrelated resources.
For several GPUs, repeat with a distinct project/env/state/network/port selection
and one reserved GPU UUID per managed instance. Share the existing GPU lease
volume across cooperating controllers. Actual multi-GPU validation remains
pending; independent configuration is not hardware proof.

### Optional LightWan A14B NVFP4 profile

Prepare the added profile explicitly; preparation defaults and existing models
remain unchanged:

```sh
docker compose --project-directory . --env-file "$VIDEO_ENV" \
  -f deploy/compose/assets.yml run --rm --build model-tools lightx2v \
  --model lightwan2.2-t2v-a14b-nvfp4
python3 src/video_runners/tools/prepare_engines.py lightx2v
```

The pinned asset plan downloads base configuration, tokenizer, T5 and VAE files,
plus two pinned NVFP4 expert files into the external model volume. It skips the
unused BF16 transformer shards and never removes existing cached models. The
prepared LightX2V image contains the new configuration. Keep the generated
`.engine-images.env` when starting/recreating the existing Compose selection.

Select `lightwan2.2-t2v-a14b-nvfp4` in the individual LightX2V catalog, or
`lightx2v-lightwan2.2-t2v-a14b-nvfp4` in the combined catalog. Follow the normal
[policy-update procedure](#stop-restart-and-update) before replacing an active
controller's trusted catalog. The profile uses four trained steps, 81 frames at
16 FPS, sparse attention, CPU text-encoder offload and GPU-resident NVFP4 experts.
It does not accept negative prompts; sampling recipe controls remain engine
configuration. Its trusted host-memory limit is 32 GiB.

The [5090 pilot](../validation/reports/video-quality-2026-10-16.md) delivered both
832×480 and 1280×720 clips. The 720p run sampled about 31 GiB of VRAM: treat it as
a tight, measured workload, not a guarantee that longer/larger jobs fit. No paid
or persistent-delivery check was added for this profile. Full-precision A14B and
NVFP4 LightWan are distinct checkpoints and launch recipes.

## Use your existing Livepeer orchestrator

Production always connects to an existing `livepeer/node`. Configure:

```dotenv
ORCHESTRATOR_URL=http://192.0.2.10:8935
RUNNER_URL=http://192.0.2.20:8989
RUNNER_BIND_HOST=192.0.2.20
RUNNER_PORT=8989
BOOTSTRAP_SECRET=the-existing-nodes-registration-secret
```

Use private LAN/VPN addresses. The runner needs the node's registration/callback/
trickle endpoints; the node needs the advertised runner URL. Grant the runner's
literal IP and port on the node, for example `--runner-grants=192.0.2.20:8989`, and
match its bootstrap secret without replacing its unrelated settings.

For a node on the same Docker host, select the small ingress overlay explicitly:

```dotenv
EXISTING_ORCHESTRATOR_NETWORK=orchestrator-net
EXISTING_RUNNER_IP=172.30.100.60
ORCHESTRATOR_URL=http://orchestrator:8935
RUNNER_URL=http://172.30.100.60:8989
```

```sh
docker compose --env-file "$VIDEO_ENV" --env-file .engine-images.env \
  -f compose.prod.yml -f deploy/compose/ingress.yml up -d --build --wait
```

Here `orchestrator-net` is an example external Docker network, and `orchestrator`
is an example node DNS name on that network. Reserve a free address in the actual
network's subnet and grant its literal `IP:8989` on the node. Prefer that same literal IP in `RUNNER_URL`; this avoids dependence on
container DNS when forwarding jobs. The overlay attaches only the runner, gives it the stable
`<COMPOSE_PROJECT_NAME>-runner` alias and replaces published ports with loopback
admin only. Use the same file selection for every lifecycle command, including
shutdown. `USE_EXISTING_ORCHESTRATOR=1` remains an initializer/recovery-tool hint;
it does not select files or overlays for direct Compose commands.

Admin requires a separate bearer token even on private Docker networks.
Controller, proxy and engine ports are never published. Existing public/pricing
catalogs remain separate from trusted launch policies. See the
[configuration guide](configuration.md), [node/signer guide](node-deployment.md)
and [security policy](../../SECURITY.md).

## Persistent downloads and state

These are **external named Docker volumes**, created before Compose starts:

| Env setting               | Default volume                 | Contents                                                                             |
| ------------------------- | ------------------------------ | ------------------------------------------------------------------------------------ |
| `HF_CACHE_VOLUME`         | `livepeer-video-hf-cache`      | Pinned Diffusers snapshots, Hugging Face blobs and preparation receipts              |
| `MODELS_VOLUME`           | `livepeer-video-model-weights` | Original-layout LightX2V checkpoints and optional converted H3 weights               |
| `ENGINE_CACHE_VOLUME`     | `livepeer-video-engine-cache`  | Torch downloads and TorchInductor, Triton, CUDA and vLLM caches, separated by engine |
| `CONTROLLER_STATE_VOLUME` | `<project>-controller-state`   | Recorded container IDs, selected model, operations and recovery state                |
| `GPU_LEASE_VOLUME`        | `livepeer-video-gpu-leases`    | Host-local per-GPU locks shared by managed controllers                               |

Containers and projects can be rebuilt or removed without downloading the weights again. **Both `down` and `down -v` preserve external volumes.** Avoid `docker volume rm` and volume-pruning tools for these volumes. Images live in Docker's image store rather than volumes; preserve the staged images too if you want offline restarts.

Asset volumes can be shared across these engine deployments. Give each deployment its own state volume. All managed deployments on this daemon must use the **same GPU lease volume** so they cannot claim the same GPU UUID simultaneously. This is cooperative exclusion; it cannot stop unrelated GPU applications or controllers using a different lease volume. External and bundled modes do not acquire the managed GPU lock.

Use a durable local Docker data directory with enough capacity and back it up. External means that Compose does not own the volume lifecycle; it does not mean that the volume is replicated or protected from a disk failure. Controller state and locks require a local filesystem with reliable file locking and atomic rename semantics. Stop managed engines before backing up state or relocating Docker storage.

Inspect without exposing credentials:

```sh
docker volume inspect livepeer-video-hf-cache livepeer-video-model-weights
docker system df
```

`HF_CACHE_DIR` and `MODELS_DIR` apply only to bundled deployment. Separate deployments use the volume names above. Production controller catalogs permit trusted named-volume mounts; callers cannot choose mount sources.

## Stage images and pinned weights

```sh
python3 src/video_runners/tools/prepare_engines.py all
# Or prepare just sglang, vllm-omni, or lightx2v.
for engine in sglang vllm-omni lightx2v; do
  docker compose --project-directory . --env-file "$VIDEO_ENV" -f deploy/compose/assets.yml run --rm --build model-tools "$engine"
done
```

The image helper reuses existing pinned images, builds an engine-only LightX2V image from pinned source on upstream's CUDA 13 RTX 5090 base, and records immutable references in ignored `.engine-images.env`. Run it against the deployment daemon. Local image IDs cannot be pulled elsewhere; distribute LightX2V through your registry by digest when needed.

The CPU-only preparation container downloads directly into the external volumes. It uses repository revisions from [`configs/model-assets.json`](../../configs/model-assets.json), records receipts under `livepeer-assets` in the Hugging Face volume, and sets the offline `main` ref to the pinned revision. Repeating preparation reuses downloaded files. Interrupted downloads can be resumed by repeating the same command. Optional `HF_TOKEN` is passed only to the preparation tool by managed deployments.

The loop above stages **one default model per engine**, not every large catalog entry:

- SGLang: `FastVideo/FastWan2.1-T2V-1.3B-Diffusers`.
- vLLM-Omni: `Wan-AI/Wan2.2-TI2V-5B-Diffusers`.
- LightX2V: `Wan-AI/Wan2.1-T2V-1.3B` in the original checkpoint layout.

Stage another model explicitly before selecting it:

```sh
docker compose --project-directory . --env-file "$VIDEO_ENV" -f deploy/compose/assets.yml run --rm --build model-tools sglang --model wan2.1-t2v-1.3b
docker compose --project-directory . --env-file "$VIDEO_ENV" -f deploy/compose/assets.yml run --rm --build model-tools vllm-omni --model wan2.2-t2v-a14b
docker compose --project-directory . --env-file "$VIDEO_ENV" -f deploy/compose/assets.yml run --rm --build model-tools lightx2v --model minimax-h3-4step
```

The last command downloads H3's pinned source components and Turbo LoRA but reports incomplete preparation until its INT8 DiT is converted. With the staged LightX2V image:

```sh
docker run --rm --runtime=runc --entrypoint python3 \
  -v livepeer-video-model-weights:/models \
  livepeer-video-lightx2v-engine:local \
  /opt/lightx2v/tools/convert/converter.py \
  --source /models/MiniMax-H3/transformer --output /models \
  --output_name minimax_h3_int8 --model_type h3 \
  --quantized --linear_type int8 --device cpu --single_file
docker compose --project-directory . --env-file "$VIDEO_ENV" -f deploy/compose/assets.yml run --rm --build model-tools lightx2v --model minimax-h3-4step
```

Substitute your configured model volume name. H3 needs its Diffusers components, including its audio components, as described by the pinned [LightX2V H3 guide](https://github.com/ModelTC/LightX2V/blob/8e86555809efd20138d3a4e1f937ee306cdf0ee0/scripts/minimax_h3/README.md). H3 and full-precision vLLM Wan A14B remain optional large-model templates without a successful RTX 5090 generation check. The separate LightWan NVFP4 profile above has its own 480p/720p pilot evidence.

Managed engines run offline and cannot pull images or download missing weights through the controller. Review the trusted [`configs/controller/`](../../configs/controller) catalogs separately from the public request defaults in [`models/`](../../models). SGLang allows 48 GiB host RAM: its text encoder exceeded the original 16 GiB cgroup limit during hardware testing. Host RAM and GPU VRAM are separate limits. Other model limits and offload flags must also be validated on the target host.

## Check preparation before startup

Preparation now records the pinned plan plus a file inventory, including extra
and locally converted required weights. Check a selected model without importing
the download client or changing saved assets:

```sh
docker compose --project-directory . --env-file "$VIDEO_ENV" \
  -f deploy/compose/assets.yml run --rm model-tools sglang \
  --model fastwan2.1-t2v-1.3b --check
```

Use model-tools built from this checkout or a release containing these checks.
Older receipts without inventories fail with corrective guidance. Repeat the
ordinary preparation command to reuse cached downloads and record an inventory;
the check itself never upgrades a receipt or downloads files. It checks plan
identity, required recorded files and sizes, nonempty weights and the offline
Hugging Face `main` ref. It rejects paths escaping their asset volume. This is a
presence/size check, not a full weight checksum or an inference test.

After staging assets and pulling/building the selected service images, inspect
the managed deployment on its Docker host:

```sh
python3 src/video_runners/tools/init_deployment.py --check \
  --env-file "$VIDEO_ENV" --compose-file compose.prod.yml \
  --model sglang-fastwan2.1-t2v-1.3b \
  --model lightx2v-wan2.1-t2v-1.3b \
  --model vllm-omni-wan2.2-ti2v-5b
```

Use IDs from the actual public and trusted catalogs. Repeat `--model` only for
profiles this instance will support; unselected optional models need no weights.
Without `--model`, a nonempty Compose `MODEL` is checked. A blank `MODEL` requires
explicit IDs because runtime startup may restore a previous controller selection.
The checked list does not change that selection: set `MODEL` to a checked profile
for deterministic startup, or review the controller's restored selection separately.
For individual-engine catalogs omit the combined engine prefix. Custom profiles
can supply a matching pinned `--assets-manifest`; revisions must be full commit
hashes and model directories/filenames must stay relative to their asset volumes.

The check resolves Compose privately, validates the trusted policy, token
agreement, engine network, Docker API, selected GPU UUID, host-RAM limits,
available service/engine images, external volumes and prepared assets. It emits
JSON with `ready`, individual checks and corrective hints; failure exits 1.
It creates no Docker resources and never pulls/builds images or starts engines.
Captured Compose output, command errors and credential values are not printed.

`.engine-images.env` is included when present. Add `--extra-env-file "$RELEASE_ENV"`
for published CPU references, or repeat it for other explicit overrides. Repeat
`--compose-file` in deployment order for supporting recipes; use `compose.dev.yml`
for managed development. This preparation check deliberately supports managed
Compose deployments; bundled/external workflows remain unchanged.

The checker needs a local Unix-socket daemon and read access to its volume data.
If volume data is inaccessible to the host process, run the CPU model-tools asset
check above rather than interpreting unreadable files as prepared. GPU UUID
presence does not establish container GPU access, available VRAM or lease
ownership. Toolkit operation, engine readiness, discovery, payment capability
and generation still require their separate validation tiers.

## Generate, inspect, and switch

For the local demo node, use its configured `ORCHESTRATOR_PORT` (default 8935):

```sh
uv sync --locked
uv run video-client --discovery http://127.0.0.1:8935/discovery --list
uv run src/video_runners/tools/validate_gpu.py --engine sglang \
  --model sglang-fastwan2.1-t2v-1.3b \
  --discovery http://127.0.0.1:8935/discovery --mode both
```

The validation helper submits once per requested delivery mode, saves MP4s and a PNG preview, decodes every frame, checks changing frames and records hashes, dimensions, frame count and request duration. It never automatically resubmits an uncertain generation. For individual-engine deployments omit the combined catalog prefix in the model ID.

To test all three default models, including actual engine switching, use an idle combined deployment:

```sh
uv run src/video_runners/tools/validate_all.py --env-file "$VIDEO_ENV"
```

This reads the private admin credential without printing it, switches through the three prepared models, generates both delivery modes and restores the initial model after success. It refuses to start with active work or reserved sessions and stops on the first failure for inspection. Supply `--discovery` and `--admin-url` for different endpoints; the defaults use the local demo node and loopback admin port from the env file. Results go under a fresh run directory in `artifacts/gpu-validation` and are ignored by Git. See [validation runs](validation-runs.md) for receipt fields, measured versus expected image identities, host serialization and cleanup.

For repeated workloads at the configured resolution, select a model first and use:

```sh
uv run src/video_runners/tools/validate_gpu.py --engine vllm-omni \
  --model vllm-omni-wan2.2-ti2v-5b --catalog-defaults \
  --mode both --repeat 2 --clips 2 \
  --gpu GPU-your-reserved-uuid --engine-container VERIFIED_ENGINE_ID
```

This makes two single-shot requests and two persistent sessions with two clips each. Optional `--width`, `--height` and `--num-frames` override the profile. The validator checks actual dimensions and frame counts. Host-side telemetry samples NVIDIA memory and cgroup v2 memory every approximately half second, records the cgroup lifetime memory peak and OOM count, and separates anonymous memory from file cache. Sampled GPU maxima can miss brief peaks; cgroup memory includes reclaimable cache and is not the process's resident heap size.

To exercise recovery on an idle managed deployment connected to the **free offchain test node**:

```sh
sudo uv run src/video_runners/tools/validate_recovery.py --engine sglang --env-file "$VIDEO_ENV"
```

This deliberately disconnects a client, stops an active persistent session, kills an idle engine, kills an engine during inference, crashes the runner and restarts its controller. It verifies durable engine identity and trusted policy before interruption, observes at most one running engine in the namespace, waits for discovery, and generates a fresh clip after every recovery. The session-stop case also checks that concurrent generation receives HTTP 503. It never restarts the Docker daemon or other projects. `--cases` selects individual checks. Run it on the Docker host with access to its controller state volume; keep the host's `.env` and `.engine-images.env` aligned with the running deployment. This fault harness does not support paid requests and refuses priced discovery. Use `validate_gpu.py` or `validate_all.py` with `--signer` for paid generation checks.

`MODEL=` restores the last selected model, or uses the catalog default initially. A nonempty `MODEL` explicitly overrides that choice each startup. Registration occurs after engine readiness. For combined managed deployments, select an engine-prefixed ID with the authenticated admin endpoint:

```sh
# Set RUNNER_ADMIN_TOKEN separately; do not print the private env file.
curl --fail-with-body -X POST \
  -H "Authorization: Bearer $RUNNER_ADMIN_TOKEN" \
  http://127.0.0.1:8990/admin/model \
  -d '{"model":"vllm-omni-wan2.2-ti2v-5b"}'
```

Allow the request to stay open while active work drains and the next model loads.
A concurrent switch returns 409. Graceful drain waits up to 120 seconds, configurable
with `SWITCH_DRAIN_TIMEOUT_S` in Compose or `--switch-drain-timeout` on the runner
CLI (positive and finite). On expiry, HTTP 409 leaves the active job and its
registration intact and restores admission when the engine state permits it.
New work is refused while draining. The deadline applies to waiting for active
work, including single-shot response completion and the node's acknowledgement
that delivery has ended; model startup and rollback retain their own profile
timeouts. Finishing inference alone does not permit unregistering a response
that the node is still delivering.

To interrupt work explicitly, send the same authenticated request with
`{"model":"lightx2v-wan2.1-t2v-1.3b","force":true}` using a model ID from your
catalog. `force` must be a JSON boolean; omission is graceful. A forced switch
cancels the active task, confirms the owned engine has stopped and waits for
task cleanup before activating a replacement. Owned-engine stop and active-task cleanup share a separate
120-second bound. Stop errors/timeouts return an error and keep admission closed
with recovery required. Cancellation acknowledgement alone never proves idle.
A force request can reload the current model. External mode refuses switching,
including force. Interrupted generations are never automatically resubmitted.

Only one engine is active; switching causes downtime and closes persistent
sessions after draining or explicit interruption. Failed activation restores
the last good model when possible. The runner waits for that previous profile's
startup timeout plus 90 seconds for controller reconciliation before attaching
and registering the restored engine. This is a bound, not a guaranteed load time.
Controller operations use idempotent IDs for
lost-response retries, with a bounded 128-operation history. Runner admin calls
are synchronous; do not assume the controller's operation ID makes a repeated
force request safe after an ambiguous response. Inspect status before acting.

External mode launches the same configured model as the runner, monitors backend health, and refuses runtime switching. After a failed or interrupted job whose idle state is unknown, it requires an operator restart of the engine and runner. Managed and bundled modes reset their owned engine before readmission. A cancellation acknowledgement does not prove that GPU execution stopped; unknown generation outcomes are never automatically resubmitted.

After three consecutive failed health checks, managed and bundled modes also attempt one owned-engine reset once the GPU job lock is idle. New work stays unavailable during recovery. A failed reset remains unavailable for operator inspection instead of looping through model restarts. External mode continues to wait for its operator-owned backend.

During active GPU work, a failed health probe blocks new admission but preserves
the existing registrations. Unregistering would make the node cancel its active
request, including work that is still loading model weights. Health recovery
restores availability without replacing those registrations. Once the GPU lock
is idle, normal withdrawal/recovery applies. Engine job deadlines, explicit
cancellation and uncertain-job reset requirements still apply.

## Stop, restart, and update

For private operational counters and timing histograms, see the
[monitoring guide](monitoring.md). Metrics use the existing bearer-authenticated
admin listener; no metrics route is published through the orchestrator.

```sh
docker compose --env-file "$VIDEO_ENV" --env-file .engine-images.env -f compose.prod.yml stop -t 150 runner
docker compose --env-file "$VIDEO_ENV" --env-file .engine-images.env -f compose.prod.yml down
# Later, reuse exactly the same private env and volumes:
docker compose --env-file "$VIDEO_ENV" --env-file .engine-images.env -f compose.prod.yml up -d --wait --wait-timeout 3600
```

Stop the runner before the controller and proxy so it can deregister and deactivate. Managed engines are created by the controller and are not Compose services. Keep state even though the engine container is disposable. Do not change image references, catalog, namespace, GPU, mounts, or engine network while a recorded engine exists: configuration drift intentionally blocks mutation. Deactivate using the old configuration first, then update.

Shutdown refuses new admin switches and cancels an in-flight runner switch before
final deactivation, preventing it from starting an engine after shutdown.
Managed shutdown waits for a controller activation/recovery already accepted,
then requests and confirms deactivation. Waiting and deactivation share a
120-second budget. Both root Compose files give the runner a 150-second stop
grace period. A controller that remains busy, becomes unavailable or cannot
deactivate causes a visible shutdown error; it does not establish that its engine
is stopped. Inspect controller status and recorded owned resources before
stopping the controller/proxy or reusing the GPU.

After a startup/recovery failure, an authenticated controller deactivation is
allowed once the in-progress operation has ended. It still verifies every
recorded resource and refuses unrecorded containers or configuration drift. New
activations remain blocked in the error state. A successful deactivation clears
the error and disables restoration until an explicit activation; it preserves
the last-good model and durable journal.

Controller restart resets recorded engines before admission to clear potentially orphaned work. An interrupted activation recovers the last good model; interrupted deactivation remains stopped. The state-directory lock excludes duplicate controllers using the same state volume; the shared GPU lease excludes different managed deployments claiming that GPU.

A crash between Docker creation and durable recording can leave an unrecorded container. The controller fails closed instead of adopting it by a forgeable label. Inspect state, image, mounts and GPU from the host, then reconcile only the verified owned resource. Do not delete state or arbitrary label matches to bypass recovery.

```sh
docker ps -a --filter label=io.livepeer.video.owner=video-engines
docker logs --tail 100 VERIFIED_CONTAINER_ID
docker compose --env-file "$VIDEO_ENV" --env-file .engine-images.env -f compose.prod.yml logs --tail 100 runner controller
```

The proxy intentionally denies logs, exec, image management, builds, networks and volumes. Its exact routes use Docker API v1.51; the deployment daemon must support that API.

## Verify without a GPU

```sh
tests/e2e/managed.sh
TEST_ENGINE=all tests/e2e/managed.sh
```

These checks generate CPU fixture videos through both delivery modes, switch models/APIs, restart the controller and runner, and test proxy restrictions. Each invocation uses unique project resources and removes only its own temporary volumes. `TEST_ENGINE=sglang`, `lightx2v`, and `vllm-omni` exercise the real public catalogs with substituted CPU backends; they do not establish GPU compatibility.

## Shared-host security

Only the proxy mounts the Docker socket. Only the controller joins its private Docker API network. The runner calls a token-authenticated controller API and supplies only catalog model IDs and operation IDs. Trusted configuration fixes images, commands, volumes, network and GPU.

The pinned [Tecnativa proxy](https://github.com/Tecnativa/docker-socket-proxy) uses an [exact route policy](../../configs/docker-socket-proxy.cfg). It restricts methods and paths, not request bodies or resource ownership. The controller remains trusted: a compromised controller could misuse allowed Docker operations against other workloads. A separate daemon/account or dedicated host provides a stronger boundary. See [SECURITY.md](../../SECURITY.md) and the [phased rollout](../design/engine-container-rollout.md).

## Advanced bundled and external recipes

These retain existing runtime ownership options. Supporting files below use
`--project-directory .` so builds, bind mounts and shared service references are
resolved from the repository root. They are real sources, not aliases.

Bundled mode starts a local free orchestrator and a runner-owned engine process:

```sh
ENGINE=stub docker compose --project-directory . --env-file /dev/null \
  -f deploy/compose/bundled.yml up -d --build --wait
# For a real bundled GPU engine, use a reviewed private env and add:
# -f deploy/compose/gpu.yml
```

Bundled mode retains its `HF_CACHE_DIR`/`MODELS_DIR` host bind mounts and existing
engine base-image defaults. Initialize the bind directories with the intended
ownership before starting a non-root backend where necessary. These are distinct
from the managed named-volume model; the default operator stacks use managed mode.

External mode uses a CPU runner attached to a Compose/operator-owned engine.
Initialize with `--mode external --engine sglang` (or another individual engine).
`EXTERNAL_ENGINE_IMAGE` chooses the image; the initializer selects the pinned
SGLang/vLLM image or the existing local LightX2V/stub image. Prepare GPU images and
weights first. `GPU_ID` selects the device for the external GPU overlay; set it
to the intended UUID on multi-GPU hosts.

```sh
docker compose --project-directory . --env-file "$VIDEO_ENV" \
  -f deploy/compose/external.yml -f deploy/compose/engine-gpu.yml \
  --profile local-orchestrator up -d --build --wait
```

The local-node profile is optional. Omit it when connecting to an existing node
and set the private URLs, secret and bind address; add `ingress.yml` for same-host
Docker connectivity. For an external CPU stub, initialize `--engine stub --mode
external`, build its image with `docker compose --env-file "$VIDEO_ENV" -f
compose.dev.yml build engine-image`, and omit the GPU overlay. External mode
refuses runtime model switches and leaves engine restart/recovery to the operator.

## Compose file purposes

| File                            | Purpose                                                                |
| ------------------------------- | ---------------------------------------------------------------------- |
| `compose.prod.yml`              | Managed production provider only                                       |
| `compose.dev.yml`               | Complete managed development stack                                     |
| `deploy/compose/assets.yml`     | One-shot downloads into external persistent volumes                    |
| `deploy/compose/signer.yml`     | Optional payer-side signer, often on another machine                   |
| `deploy/compose/ingress.yml`    | Same-host existing-node attachment; removes generation host publishing |
| `deploy/compose/bundled.yml`    | Retained bundled ownership recipe                                      |
| `deploy/compose/gpu.yml`        | GPU assignment for the bundled runner                                  |
| `deploy/compose/external.yml`   | Retained externally owned engine recipe                                |
| `deploy/compose/engine-gpu.yml` | GPU assignment for the external engine                                 |

The old root Compose symlinks, root Python facades and `scripts/deploy.sh`
selection wrapper are removed. See the [command migration](repository-layout.md)
for their replacements. Existing routes, delivery modes and lifecycle behavior
are unchanged.
