# Versioned CPU container releases

Application releases and operator engine preparation are independent. Publish the
CPU images with this workflow; prepare GPU engines and weights on the provider
host using the [deployment guide](container-deployment.md#stage-images-and-pinned-weights).
Use the existing production/development Compose entry points.

## Images and ownership

| Published CPU image          | Contents                                                        |
| ---------------------------- | --------------------------------------------------------------- |
| `livepeer-video-runner`      | Runner and SDK integration                                      |
| `livepeer-video-controller`  | Lifecycle controller with its own entrypoint and authority      |
| `livepeer-video-model-tools` | Weight preparation tools, invoked only when needed              |
| `livepeer-node`              | Pinned upstream node, used separately as orchestrator or signer |

Operators pull the pinned upstream SGLang and vLLM-Omni images. For LightX2V,
the existing preparation helper pulls the upstream base and builds a local
engine image with pinned server code/configuration. Model downloads go into
persistent external volumes. The controller starts, stops and switches those
prepared engines through its trusted launch policy.

The CPU publisher never builds, pulls, pushes or runs GPU engines. It requires
no engine baseline. Its manifest has `schema_version: 2` and `scope: cpu`;
`release.env` contains only `RUNNER_IMAGE`, `CONTROLLER_IMAGE`,
`MODEL_TOOLS_IMAGE` and `LIVEPEER_NODE_IMAGE`. Operator engine references remain
in the separate `.engine-images.env`. The earlier unreleased combined-bundle
format is refused before Docker actions. Optional engine-image distribution is
an operator decision outside this CPU release workflow.

Tags identify versions for humans; deployments use recorded
`repository@sha256:…` references. Configure registry tag immutability if needed.
Node labels identify its upstream source/revision. Other CPU labels identify
this repository's source revision. All images target `linux/amd64`.
An image build does not establish GPU or paid-operation readiness.

## Publish CPU images

Use a clean checkout, Docker Buildx and an existing registry login scoped to the
selected namespace. Registry addresses, namespaces and credentials are private
operator settings. A GPU, model data and payer credentials are unnecessary.
Buildx uses the `default` builder unless `RELEASE_BUILDER` selects another
existing builder. CPU builds need dependency/node build storage; they download
no CUDA base or model weights and install no recurring worker service.

```sh
export CONTAINER_REGISTRY=registry.example.com
export CONTAINER_NAMESPACE=operator
export RELEASE_TAG=source-or-version-tag
# Use your credential manager or docker login --password-stdin.
python3 src/video_runners/tools/release.py plan \
  --registry "$CONTAINER_REGISTRY" --namespace "$CONTAINER_NAMESPACE" \
  --tag "$RELEASE_TAG"
scripts/check.sh
tests/e2e/compose-config.sh
python3 src/video_runners/tools/release.py publish \
  --registry "$CONTAINER_REGISTRY" --namespace "$CONTAINER_NAMESPACE" \
  --tag "$RELEASE_TAG" --output "artifacts/releases/$RELEASE_TAG"
```

Publish builds the four CPU roles, checks each entrypoint with `--help` using
`runc` and no network, pushes it and records its registry digest. It starts no
orchestrator, signer or inference service. The output directory must be new.
Partial failure retains completed-image evidence in a failed manifest and
produces no complete release env. Publication across repositories is not atomic;
inspect failures before creating another attempt. No daemon prune is performed.

Optionally add `--reuse-manifest /private/previous-cpu-release.json` to `plan`
and `publish`. This reuses only the node image when its upstream source,
Dockerfile and platform match a complete published CPU release. Otherwise node
is rebuilt. Runner, controller and model-tools always build for the new source.
Reused node digests are not pulled, rebuilt, smoke-run or pushed. Original node
tag/source provenance and previous evidence are preserved. Engine
source, configuration or image changes never require an engine publication to
release CPU images.

Keep `manifest.json` and `release.env` together; output under `artifacts/` is
excluded from Git. These files contain references/provenance, never credentials.
Treat the manifest as trusted deployment input and review its source and
validation evidence before sharing it.

## Pull CPU images and prepare the provider

Check out the manifest's `source_revision` first. The pull command requires a
clean matching checkout, validates known CPU build/deployment inputs and pulls
only the four CPU digest references. It refuses an existing output env file.
It does not change the operator's engine env, models, volumes or keys.

```sh
export VIDEO_ENV=/private/provider.env
export RELEASE_ENV=artifacts/selected-cpu-release.env
python3 src/video_runners/tools/release.py pull \
  --manifest /private/release/manifest.json --env-file "$RELEASE_ENV"

# On the provider's Docker host, prepare only the engines/profiles it will serve.
# Repeat these two commands for each selected engine; model/profile details are
# in the deployment guide. Existing pinned images and cached weights are reused.
export ENGINE_TO_PREPARE=sglang
python3 src/video_runners/tools/prepare_engines.py "$ENGINE_TO_PREPARE"
docker compose --env-file "$VIDEO_ENV" --env-file "$RELEASE_ENV" \
  -f deploy/compose/assets.yml run --rm model-tools "$ENGINE_TO_PREPARE"

# After all selected engines and weights are ready:
docker compose --env-file "$VIDEO_ENV" --env-file "$RELEASE_ENV" \
  --env-file .engine-images.env \
  -f compose.prod.yml up -d --no-build --wait --wait-timeout 3600
```

Provider initialization, external volumes and trusted launch policy still follow
the [deployment guide](container-deployment.md). Release and engine env files
supply separate settings; neither replaces the private provider env. Locally
prepared LightX2V uses its immutable local image ID, which is accepted by the
existing managed policy. No registry publication of that image is required.

The development stack and optional signer accept the same CPU image overrides.
Ordinary development retains local build defaults. Use `--no-build` for published
Compose deployments; omit `--build` when running published model-tools.
Prepared engine images live in Docker's image store; weights/caches use external
volumes. Preserve both for offline restarts.

## Manual GitHub CPU release workflow

The [workflow](../../.github/workflows/release.yml) is manually triggered; PRs and
normal pushes do not publish. It runs checks and publishes CPU images on a
GitHub-hosted Linux worker. It needs no engine baseline, GPU, models or payer keys.

Set repository variables `CONTAINER_REGISTRY`, `CONTAINER_NAMESPACE`, and secrets
`CONTAINER_REGISTRY_USER`, `CONTAINER_REGISTRY_PASSWORD`. Optionally set
`CONTAINER_NODE_RELEASE_MANIFEST` to a complete prior CPU manifest for same-source
node reuse. Leaving it unset builds all four CPU roles. Registry credentials go
through stdin and are never embedded in YAML, images or artifacts. A local
Docker login does not configure GitHub credentials.

Fast checks, Compose resolution, optional node compatibility checks, CPU image
entrypoint checks and manifest/env artifacts are part of this workflow. The
separate integration, hardware and payment gates remain in the
[verification guide](../reference/checks.md). Local implementation does not push
this workflow to GitHub or configure repository variables/secrets.
