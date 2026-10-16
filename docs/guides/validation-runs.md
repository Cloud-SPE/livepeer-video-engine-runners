# Isolated validation runs and evidence

Use the [check tiers](../reference/checks.md) to choose a workflow. Fast checks
start no services. The commands below are explicit Docker or deployed-stack
operations; CPU fixtures do not establish GPU or paid readiness.

## CPU Docker runs

```sh
tests/e2e/bundled.sh
TEST_ENGINE=all tests/e2e/managed.sh
# Other managed catalog selections: stub, sglang, lightx2v, vllm-omni.
```

Both entry points use [cpu_harness.py](../../src/video_runners/tools/cpu_harness.py).
Their options are in the [generated reference](../reference/configuration.md).
Use `--output-dir /path/to/evidence` to choose an output root. Each invocation
creates a fresh `vr-<worktree-hash>-<random-run-id>` directory and Docker project.
The worktree hash distinguishes checkout paths; the random suffix distinguishes
repeated or concurrent runs from the same checkout.

Each run has its own image tags, ports, subnets, networks and temporary state.
Build labels make image ownership observable. Managed fixtures use the built
stub image's immutable ID in a separate generated controller policy. Bundled
fixtures bind empty run-specific cache/model directories. Neither uses production
wallet/model/cache volumes, host payer keys or production image tags. Existing
deployment Compose definitions and their defaults remain unchanged; the harness
adds a private per-run overlay. Builds reuse normal BuildKit caches without pruning
them. `BUILDX_BUILDER` defaults to `default` and can be explicitly selected.

A cooperative setup lock reserves networks while choosing subnets. Port sockets
remain reserved through builds and are released under the setup lock just before
Compose startup. Unrelated host processes can still race a port allocation; a
failed startup is recorded and cleaned up, never resolved by taking another
workload's resources. `SKIP_BUILD` is no longer used: every run builds its own
image identities, using the normal build cache.

The existing `tests/e2e/e2e.sh` remains a workload-only check against an explicitly
selected, running CPU test stack. It does not create or own that stack. CI and
isolated local testing use the bundled/managed wrappers instead.

## Receipts and cleanup manifests

Run outputs default to `artifacts/cpu-validation/<run-id>/` for CPU tests and
`artifacts/gpu-validation/<run-id>/` for generation/switching. Recovery uses its
configured output root with the same unique-directory convention. These paths
are ignored by Git. Repeating a command creates new evidence and does not
overwrite a previous run's clips, logs or receipts.

`receipt.json` uses `schema_version: 1` and records:

- `run_id`, optional `parent_run_id`, workflow `kind`, start/finish timestamps;
- source Git revision, dirty flag and worktree identity;
- allowlisted `inputs`, completed `results`, final `status` and `outcome`;
- an error type on failure, without copying the exception, CLI arguments,
  private env, signer/discovery URLs or credential values into the receipt.

Generation inputs include the pinned asset revisions, expected preparation image
references, workload, seed and a hash of the fixed validation prompt. When
`--engine-container` is supplied, the GPU validator also records the inspected
container/image identities. Without it, `observed_engine` is `null`: a preparation
pin is not proof of the deployed image. `--gpu` additionally records the selected
GPU's UUID/name/driver and enables host memory sampling. These measurements
require running on the deployment host. Recovery supplies the verified engine
identity to its fresh-generation child automatically.

Successful checks use `status: passed` and `outcome: verified`; the workflow kind
and inputs define what was checked. Readiness-only recovery explicitly uses
`outcome: readiness_only`. Failures retain partial results and an unknown outcome.
A process killed before finalization leaves a running receipt with unknown
outcome. None of these states authorize automatic generation resubmission.

CPU `resources.json` separately records the daemon identity, per-run images and
Docker-issued resource IDs with configuration fingerprints. It contains no
plaintext service environment. Container fingerprints normalize Docker's mount
response order while preserving every mount field; a changed source, permission
or propagation mode still blocks cleanup. Cleanup checks recorded identities and ownership
before removal, stops the verified runner first, and removes only owned test
containers, networks, temporary volumes and image tags. Managed engines must also
match the controller's durable ownership record and generated trusted policy.
Labels alone do not authorize engine cleanup.

On successful teardown, `cleanup: complete` is retained and private env/catalog/
overlay files are removed. Evidence remains. If ownership, configuration, image
tags or the daemon differ, cleanup fails for operator review; it never prunes the
daemon. Inspect the receipt, manifest and local logs, reconcile the mismatch, then:

```sh
uv run --locked python src/video_runners/tools/cpu_harness.py --cleanup /path/to/run/resources.json
```

An unknown engine or an unavailable controller may prevent reading durable
ownership. Preserve its state volume for inspection; do not remove it to make the
cleanup check pass. A killed harness can require manual reconciliation of
unrecorded creation outcomes. This cleanup interface is for CPU test resources,
not production model or wallet cleanup. It does not protect against a compromised
Docker daemon; see [security](../../SECURITY.md).

Run directories are mode `0700`; receipts/manifests/private env are mode `0600`.
The generated CPU catalog bind is readable by the non-root controller and
contains no credentials. CPU failures capture service logs with the run's known
tokens redacted. Review raw logs before sharing. Public reports must omit hostnames, actual
addresses, account identities, GPU UUIDs, private paths/resource names and
worktree-derived run IDs. Keep GPU type/driver, immutable image/model revisions,
workload, measurements and outcome; do not publish raw receipts or resource
manifests without checking their host-specific fields. CI uploads only the CPU receipt
and resource manifest, using a pinned artifact action with seven-day retention;
it excludes private inputs and raw logs. CI changes have no effect until pushed.

## Hardware validation coordination

Generation, cross-engine switching and recovery validators share a cooperative
same-user host lock in `/tmp/livepeer-video-<uid>/gpu-validation.lock`. A competing
invocation fails before switching, fault injection or generation. Parent tools
pass their open lock descriptor to child validators, so the whole sequence stays
serialized and child exit does not release the parent's lease. Child receipts
reference their parent run.

Run all hardware validators on the reserved GPU host under the same host user.
Different users, remote client hosts and unrelated GPU applications do not share
this lock. The controller's external GPU lease and model/cache volumes retain
their existing roles; see [deployment persistence](container-deployment.md#persistent-downloads-and-state).
The validators do not delete or recreate model volumes. GPU and paid workflows
still require explicit operator action and fresh evidence.

## Correlated lifecycle logs

The managed supervisor and controller emit JSON log messages containing lifecycle
event names and the same `operation_id` used by the authenticated controller API.
Container records/readiness/removal include model and namespace; activation and
recovery completion include phase/state. Controller recovery uses a fresh local
correlation ID. Search runner and controller logs for the operation ID, then join
container events by namespace and ID. CPU namespaces equal their run IDs.

Diagnostic fields are allowlisted in [diagnostics.py](../../src/video_runners/diagnostics.py).
They include no request prompts, authorization headers or tokens. These messages
do not alter HTTP responses, SSE/trickle events, app IDs, operation semantics or
the durable controller-state schema.
