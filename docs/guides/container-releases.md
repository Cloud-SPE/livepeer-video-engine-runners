# Versioned container releases

Use the existing production/development entry points. A release supplies immutable
image references; it does not introduce another deployment mode or Compose stack.
Private registry addresses, namespaces and credentials are operator settings.

## Images and provenance

| Image repository                 | Contents                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------ |
| `livepeer-video-runner`          | CPU runner and SDK integration; no node binary, CUDA or weights                      |
| `livepeer-video-controller`      | CPU lifecycle controller; separate entrypoint and authority                          |
| `livepeer-node`                  | Pinned upstream node, used separately as orchestrator or signer                      |
| `livepeer-video-model-tools`     | CPU weight preparation, run only when needed                                         |
| `livepeer-video-lightx2v-engine` | Pinned upstream GPU base plus pinned LightX2V source/configuration; no model weights |

SGLang and vLLM-Omni retain their digest-pinned upstream images. The release
manifest records those pins, the LightX2V build inputs, both node roles' shared
source revision, the repository revision and hashes of launch/build inputs.
Node labels identify its upstream source/revision, rather than implying that
the runner/controller are merged into that image. All release images currently
target `linux/amd64`; this does not establish ARM or new GPU compatibility.

Tags identify versions for humans. Deployments use the recorded registry
`repository@sha256:…` references; registry tags themselves can be overwritten.
Configure tag immutability in the registry if required. A new build/registry
digest is not fresh hardware-inference evidence.

## Initial or changed-engine publication

Use a clean checkout, Docker Buildx and a registry login with push access to the
selected namespace. A GPU, model volumes and payer credentials are unnecessary.
The LightX2V base is large: reserve substantial Docker storage, including room
for extracted layers and node build intermediates. Buildx uses the `default`
builder unless `RELEASE_BUILDER` explicitly selects another existing builder.
No builder, daemon configuration, GPU workload or recurring service is installed.

```sh
export CONTAINER_REGISTRY=registry.example.com
export CONTAINER_NAMESPACE=operator
export RELEASE_TAG=source-or-version-tag
# Log in using your credential manager or docker login --password-stdin.
python3 src/video_runners/tools/release.py plan \
  --registry "$CONTAINER_REGISTRY" --namespace "$CONTAINER_NAMESPACE" \
  --tag "$RELEASE_TAG"
scripts/check.sh
tests/e2e/compose-config.sh
# Also run the relevant CPU/GPU validation before claiming release readiness.
python3 src/video_runners/tools/release.py publish \
  --registry "$CONTAINER_REGISTRY" --namespace "$CONTAINER_NAMESPACE" \
  --tag "$RELEASE_TAG" --output "artifacts/releases/$RELEASE_TAG"
```

Publish builds each image, runs the four CPU entrypoints with `--help` and no
network, pushes it, and records the matching registry digest. It never starts
an orchestrator, signer, inference engine or model download. It does not copy
Docker credentials into images, manifests or env files. The output directory
must be new. Partial publication retains a failed manifest with completed image
references; it produces no deployable env file. Publication across repositories
is not atomic. Inspect a failed build before creating a new release attempt.
Published images and build caches are retained; no daemon prune is performed.

This full publication is an explicit operator action for the initial engine
baseline or changed engine inputs. It is not the normal CPU CI path.

## Normal CPU publication

Reuse a trusted complete published baseline when engine inputs are unchanged:

```sh
python3 src/video_runners/tools/release.py publish \
  --registry "$CONTAINER_REGISTRY" --namespace "$CONTAINER_NAMESPACE" \
  --tag "$RELEASE_TAG" --reuse-manifest /private/engine-baseline.json \
  --output "artifacts/releases/$RELEASE_TAG"
```

Use the same `--reuse-manifest` with `plan` to preview this selection. Reuse
verifies the LightX2V base, upstream source pin, engine Dockerfile and complete
baked-configuration hash set. Changed inputs fail before publication and require
an explicit changed-engine release; they never trigger a large engine build in
normal CI. The node image is also reused when its upstream source pin matches.
A changed node source triggers a CPU node build. Runner, controller and
model-tools are built/published for the new source revision. No GPU image is
pulled, rebuilt, smoke-run or pushed on the matching reuse path.

The new manifest combines current CPU digests with the existing engine/node
digests and their original tags/source provenance. Previous evidence is not
rewritten. This keeps versioning independent while rejecting incompatible engine
reuse. Changing a weight/profile does not inherently require an image rebuild;
it still requires the relevant configuration and hardware validation.

The output includes `manifest.json` and `release.env`, both excluded from Git
under `artifacts/`. Preserve these with the release. Review source changes and
hardware evidence before distributing the manifest. Manifests are not signed;
obtain them through a trusted channel.

## Pull and deploy an existing release

Obtain the manifest, check out its `source_revision`, and retain the normal
private provider env generated by the [deployment guide](container-deployment.md).
The pull command verifies a complete publication, matching checkout launch/build
inputs and credential-free registry digests before contacting Docker. It pulls
all seven owned/upstream images and refuses to replace an existing env file.
It creates no volumes, services or model downloads.

```sh
export VIDEO_ENV=/private/provider.env
export RELEASE_ENV=artifacts/selected-release.env
python3 src/video_runners/tools/release.py pull \
  --manifest /private/release/manifest.json --env-file "$RELEASE_ENV"
docker compose --env-file "$VIDEO_ENV" --env-file "$RELEASE_ENV" \
  -f compose.prod.yml up -d --no-build --wait --wait-timeout 3600
```

Use the usual ingress overlay if the existing orchestrator needs it. Production
still connects to that existing orchestrator. The optional signer and asset
recipes accept the same release env; the signer/node image remains one upstream
image used in two separate roles. Prepare pinned weights through the normal
asset workflow; image pulls do not populate model volumes. Controller-created
engines require their images to be staged on the provider's daemon, which is why
the pull command includes GPU engines.

Stop/deactivate using the old env and catalog before updating a recorded engine.
Preserve controller state and external model/cache/wallet volumes. Follow the
[shutdown/update procedure](container-deployment.md#stop-restart-and-update).
For ordinary development, keep local image defaults and the documented local
build workflow. Do not combine digest release overrides with `up --build`.

## Manual GitHub CPU release workflow

The [release workflow](../../.github/workflows/release.yml) is manually triggered;
PRs and normal pushes do not publish images. It uses a normal GitHub-hosted Linux
worker and the verified reuse path above. No build-worker service is installed
on an operator machine. The worker needs no GPU, model data or payer keys.

Configure repository variables `CONTAINER_REGISTRY`, `CONTAINER_NAMESPACE`, and
secrets `CONTAINER_REGISTRY_USER`, `CONTAINER_REGISTRY_PASSWORD`. Set repository
variable `CONTAINER_BASE_RELEASE_MANIFEST` to the JSON contents of a trusted
complete published baseline. Update it explicitly after a changed-engine release.
It contains image references/provenance, never credentials. Use a registry
account scoped to the release namespace. Local Docker login is separate from
GitHub's credentials. Never put a registry password in YAML or an input argument.
The workflow runs fast checks, Compose resolution and baseline compatibility
checks, builds/smoke-checks the CPU images, publishes them and retains the combined
manifest/env as artifacts. Separate CPU integration,
hardware and paid gates remain those in the [verification guide](../reference/checks.md).
Adding the workflow file does not activate it on the remote repository;
repository publication and registry-variable/secret configuration remain explicit actions.
