# Provider platform v1: deferred discussion record

Recorded: 2026-10-16. Status: **deferred; not an implementation mandate**.

This records the full provider-platform plan discussed with the operator before
the scope correction on October 16. The operator subsequently explained that the
immediate goal was compatibility cleanup and simpler production/development
Compose stacks, not this broader runtime change. The
[focused cleanup record](../active/deployment-cleanup.md) takes precedence for
near-term work. Previously agreed choices below preserve discussion context;
they do not authorize feature removal or runtime changes during that cleanup.

No implementation of this plan has begun. The baseline for this record is local
commit `9f57ee6`. The [architecture](../../../ARCHITECTURE.md) and current guides
describe existing code; this document describes a possible future contract.
The comparison below records that baseline before the focused cleanup; it is
not a description of the current Compose layout.

## Motivation and original scope

The discussion began with excessive compatibility aliases, many Compose
combinations and a systemd SSH-tunnel example. It expanded into a proposed v1
provider product: one supported engine-ownership model, repeatable per-GPU
deployments, stronger lifecycle semantics and a network-first application client.

That expansion is substantive. It combines repository cleanup, deployment
consolidation, feature retirement, lifecycle enhancements and client behavior
changes. Those concerns can be delivered independently. The operator has now
requested that the immediate work address the first two only.

## Baseline implementation versus the broader proposal

| Area           | Existing implementation                                                 | Broader proposed change                                             |
| -------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Engines        | SGLang, LightX2V and vLLM-Omni HTTP adapters, images and profiles       | Retain and validate against the narrowed product contract           |
| Ownership      | Bundled, external and managed; runner CLI defaults to bundled           | Managed only; retire the other two modes                            |
| GPU isolation  | Controller state locks and shared exclusive GPU leases                  | Standardize independently repeatable one-GPU instances              |
| Docker proxy   | One socket proxy per managed deployment                                 | One shared private socket proxy per host                            |
| Switching      | Runner drains by waiting for its GPU lock without a deadline            | Bounded drain, explicit force-stop and consistent operation status  |
| Operations     | Controller already persists asynchronous, idempotent operations         | Expose the complete action through runner-facing management and CLI |
| Restart intent | Controller persists enabled/stopped state; runner startup loads a model | Preserve intentional stop across the complete startup path          |
| Rollback       | A failed activation can restore the previous model once                 | Retain and harden; intentional stop must never reactivate a model   |
| Jobs           | Single-shot, persistent sessions and optional waiting                   | Single-shot only, immediate busy rejection                          |
| Advertising    | Active model registers after readiness                                  | Preserve and verify all lifecycle transitions                       |
| Client         | Local discovery URL by default; first returned candidate selected       | Network discovery by default and safe eligible-replica selection    |
| Storage        | External weights/cache/state volumes and preparation tooling            | Explicit host-shared weights and per-instance mutable cache/state   |
| Configuration  | Public catalogs, trusted policies, pins and generated references        | Preserve authority separation; clearer host/instance settings       |
| Deployment     | Twelve canonical Compose files plus compatibility paths                 | Separate host, instance and optional client roles                   |
| Validation     | CPU harnesses and dated single-5090 GPU evidence                        | Additional lifecycle, multi-GPU and supported paid-path acceptance  |

The engine adapters, existing controller architecture, model preparation,
authentication, prices and much of the test harness would be reused. This is not
a new inference implementation, but it is considerably larger than removing
aliases and simplifying Compose.

## Provider components and ownership

1. Production deployment supplies provider components and connects to an existing
   `livepeer/node` orchestrator. It does not deploy or manage the operator's
   production orchestrator.
2. `livepeer/node` is the supported node implementation. Do not introduce a
   parallel legacy `go-livepeer` orchestrator or gateway deployment.
3. The application client uses the Python `livepeer-gateway` SDK. A payer-side
   `livepeer/node` signer handles discovery/payment integration where needed;
   there is no additional traditional gateway daemon.
4. The proposed production ownership model is managed only: CPU runner, CPU
   controller and a separate engine container. Engine dependencies and weights
   do not become part of the runner image.
5. The runner owns admission, registration and draining. It calls the
   controller's authenticated HTTP API; it does not import the controller's
   Docker implementation or receive the Docker socket.
6. The controller owns engine container creation, termination, readiness and
   recorded ownership. Requests contain approved model/operation identifiers,
   not arbitrary Docker bodies, commands, images or mounts.
7. Bundled child-process supervision and externally owned engine attachment
   would be retired under this broader plan. **That retirement is deferred and
   excluded from the focused cleanup.**

## Instances and GPUs

1. One instance consists of one runner, one controller and at most one active
   engine, assigned exclusively to one GPU UUID.
2. A server may run multiple independent instances on different GPUs. Those may
   serve different models or multiple replicas of the same model.
3. V1 disallows multiple instances sharing one GPU. Existing cooperating
   controllers use a shared GPU lease to reject duplicate assignments.
4. One engine instance spanning several GPUs is a v2 requirement. Its support
   must be validated per engine rather than inferred from other engines.
5. There is no new host-wide scheduler/controller in this proposal. Each
   instance remains independently managed.
6. One private socket proxy per host would serve the instance controllers. Only
   that proxy mounts the Docker socket. Runners and engines do not join its
   Docker API network.
7. Shared Docker hosts may run unrelated workloads. Reserve each assigned GPU
   for its runner; a cooperative lease does not reserve VRAM against unrelated
   GPU applications.
8. Socket route/method filtering is not container-ownership enforcement. A
   compromised controller still has significant daemon authority; preserve the
   trust boundary described in [Security](../../../SECURITY.md).

## Models, configuration and asset preparation

1. Ship profiles for validated SGLang, LightX2V and vLLM-Omni models. Operators
   may add compatible profiles through configuration.
2. A new profile using an existing supported API/output shape should not require
   a runner code change. A different engine protocol or output contract may.
3. Public request/default/pricing catalogs and trusted Docker launch policies
   remain separate authorities. A public catalog edit must never grant launch
   authority.
4. Trusted policy controls images, commands, GPU assignment, mounts, networking
   and resource limits. Pin preparation inputs and deployed image/weight
   identities; document explicit upgrades.
5. Prepare images and model assets explicitly before activation. Validate
   prerequisites before interrupting the current model. Switching must not
   unexpectedly initiate large downloads.
6. Model switching selects among profiles already allowed by the deployed
   configuration. Catalog or launch-policy edits require a controlled redeploy
   of affected instances, not hot execution of newly supplied launch data.
7. Keep time-metered USD/hour operator prices and signer price ceilings. This
   plan does not introduce a fixed-price-per-video payment model.

## Jobs, capacity and discovery

1. A client chooses a model; eligible-instance/replica selection is automatic.
   Respect compatibility, availability and signer price ceilings. Do not add a
   custom cheapest-first ranking scheme.
2. Discovery advertises currently running, ready instances and models.
   Configured but unloaded models appear only in management information.
3. Each request is an independent single-shot job with its own progress/result
   stream. Persistent reservations and shared long-lived output channels would
   be retired. This retirement is deferred.
4. No affinity is required between separate jobs. A job remains on its selected
   runner/engine instance while executing; no migration of an active generation.
5. If every compatible replica is busy, reject promptly. No internal waiting
   queue in v1; queueing is a v2 requirement.
6. On client disconnect, attempt cancellation. A cancellation acknowledgement
   alone is not proof that the engine is idle. If idle state is unknown, block
   new admission and reset the owned engine before reuse.
7. Never automatically resubmit a generation whose outcome is unknown. A
   definitive refusal before acceptance and an ambiguous transport failure are
   different cases; replica selection must preserve that distinction.
8. Normal SDK selection policy/order is sufficient where it satisfies these
   constraints. Do not blindly use an SDK retry helper that retries every
   exception and can replay an accepted generation.

## Management operations and state transitions

### Graceful switching

- Only an authenticated management command/API initiates switching. A generation
  request cannot load another model automatically.
- Stop new admission, allow the current generation to finish, stop the old
  engine, activate the target, verify readiness and then advertise it.
- Use a bounded, configurable drain timeout distinct from engine startup
  timeout. No numeric drain default was agreed; choose it from workload evidence.
- If draining expires, fail the requested switch without automatically killing
  the active generation or replacing its model. Reconcile admission afterward
  with the actual state.
- During transition from the old implementation, any persistent reservations
  must be closed deliberately rather than silently migrated.

### Explicit force-stop

- The operator targets a specific instance and explicitly requests interruption.
- Interrupt its work and stop its owned engine. Leave it stopped until an
  explicit start request.
- Do not affect other GPU instances or unrelated Docker workloads. Do not replay
  interrupted jobs, and do not roll back an intentional stop into a running model.

### Activation failure and rollback

- Attempt the requested model once. If activation fails, attempt one rollback to
  the last working model, with a separate readiness/startup deadline.
- The requested switch remains failed even when rollback restores service.
- Advertise the restored model only after readiness. If rollback also fails,
  leave the instance unavailable with inspectable errors; no endless loop.
- Software/image rollback during an upgrade is a separate, operator-directed
  procedure, not automatic model-switch rollback.

### Restart and interrupted-operation recovery

- First startup uses the configured initial model.
- An instance intended to run restores its last selected working model.
- An explicitly stopped instance stays stopped, with management available.
- An interrupted switch reconciles recorded owned containers and recovers the
  last good model as appropriate.
- Interrupted jobs are never replayed. Persist operator intent rather than
  interpreting every process restart as a request to activate a model.

### Operation API and observability

- Long-running actions return durable operation IDs with status/progress.
- The CLI waits and shows progress by default, but accepted work continues if
  that CLI disconnects. Reusing an operation ID must not duplicate the action.
- Preserve the existing controller operation machinery and complete the outer
  runner-facing action semantics; do not rebuild it merely to rename it.
- Provide status through CLI/API and structured Docker logs, with bounded log
  rotation and instance/model/operation/error identifiers.
- No mandatory dashboard, monitoring stack or continuously running management
  agent is required.

## Deployment and persistence

The earlier proposed layout was three canonical operator Compose roles:

```text
deploy/compose/host.yml       # Shared socket proxy and optional asset tooling
deploy/compose/instance.yml   # One runner/controller unit per GPU
deploy/compose/client.yml     # Optional local signer and read-only discovery tool
tests/...                    # Isolated CPU fixture deployments
```

This layout is part of the deferred proposal, not a promise that those files
exist or the target for the focused cleanup.

- Docker Compose CLI is the primary deployment mechanism. No Portainer-specific
  renderer, custom deployment DSL or new host scheduler.
- Host env settings plus small per-instance env settings and separate credential
  files, all operator-specific data outside the checkout.
- Host settings describe orchestrator connectivity, network and shared volumes.
  Instance settings identify the instance, GPU UUID, model/catalog and admin port.
- Weights/Hugging Face downloads are host-shared persistent storage. Mutable
  engine/compilation caches and controller state are per instance. GPU leases
  remain shared across cooperating controllers.
- All persistent volumes survive normal teardown and upgrades. Migration must
  preserve existing volume names/data before changing defaults.
- Connect an existing orchestrator either through a shared private Docker
  network on the same host or a private LAN/VPN between hosts. Verify both
  runner-to-orchestrator and orchestrator-to-runner reachability.
- Admin is authenticated and bound to loopback by default. Remote access uses
  an on-demand SSH command or an operator's private VPN. Engine/controller/proxy
  endpoints remain private; no public management dashboard.
- Replace the example persistent SSH-tunnel `.service` with documented on-demand
  access. Installing a systemd service is not a deployment prerequisite.
- Upgrade explicitly pinned versions one instance at a time, with documented
  status checks and operator-directed software rollback.

## Development and paid network validation

1. Routine development uses a Python virtual environment and CPU fixtures. Fast
   checks require no Docker daemon, GPU, remote host, wallet or funded signer.
2. Docker lifecycle integration and real hardware tests are separate explicit
   workflows. Isolate run identities and verify cleanup ownership.
3. A development machine can validate a remote provider through the Python SDK
   and a payer-side signer. Provider SSH or Docker access is not required to
   submit a client validation job.
4. Support either an existing signer URL or an optional local `livepeer/node`
   signer Compose service. Existing key/password/RPC files stay outside the
   repository and are mounted read-only; signer mutable state stays private and
   persistent. Results are saved locally.
5. Livepeer network discovery would become the default. An explicit
   orchestrator/discovery override remains available for private tests.
6. Do not modify or fork `livepeer/node`. Use its existing read-only chain CLI
   to enumerate active orchestrators/service URLs, then query their `/discovery`
   endpoints through the application client/SDK.
7. Run chain inspection as a one-shot command/native executable or unchanged
   pinned node image, not a new discovery daemon. RPC is required; wallet access
   is not required for pool inspection.
8. Report no eligible provider clearly. Do not silently fall back to the
   operator's private orchestrator and label it a network-discovery success.

### Read-only discovery feasibility evidence

The discussion included a local feasibility probe against unmodified node source
at `08081dbda0f4f7b56e362e3af4b6965bfa1b73a4`. Its standalone chain CLI was built
and used with a public Arbitrum RPC, without wallet keys or a generation call.
The active pool returned 100 orchestrators, 98 with service URIs, at block
515341803, in approximately 30 seconds. Bounded public discovery requests found
three SDK-parseable responses with four runner applications, none matching the
video-generation application IDs sought by this project.

This establishes read-only enumeration and discovery parsing feasibility for that
snapshot. It does not establish a container wrapper, eligible-provider routing,
paid video generation or global provider absence. The probe used public metadata
and SDK-compatible TLS behavior; it was not a TLS-security validation. Temporary
probe source, binary and output were removed. These are discussion-time results,
not a newly committed automated test or a replacement for release evidence.

Primary source references:

- [Pinned node chain commands](https://github.com/livepeer/node/blob/08081dbda0f4f7b56e362e3af4b6965bfa1b73a4/docs/chain.md).
- [Pinned signer discovery configuration](https://github.com/livepeer/node/blob/08081dbda0f4f7b56e362e3af4b6965bfa1b73a4/docs/signer.md#configure-discovery).
- [SDK selection implementation](https://github.com/livepeer/livepeer-python-gateway/blob/main/src/livepeer_gateway/selection.py).

## Compatibility and documentation

- Retire symlinks, root Python forwarding facades and legacy duplicate command
  paths. Give each implementation and operator action one canonical location.
- Update every internal caller, Docker mount, generated reference, CI command
  and current guide that uses a retired path. Do not retain hidden forwarding
  wrappers as a substitute for removed aliases.
- Preserve surviving generation routes, model IDs, request schemas, event shapes
  and SDK integration. Identify ownership-mode and persistent-session retirement
  as explicit breaking changes, not mechanical cleanup.
- Keep current operation instructions in canonical guides. Keep discussion
  records, plans and dated validation evidence distinct from supported behavior.
- Keep `AGENTS.md` short and navigational, with enforceable existing dependency
  boundaries and links to detailed instructions.

Only the compatibility-path cleanup is included in the immediate narrower
proposal; runtime/API retirements remain deferred.

## Original phased execution proposal

| Phase                        | Work                                                                                                                     | Exit evidence                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| 1. Record contract           | Version the v1/v2 decisions, acceptance criteria and dependencies; archive the completed harness plan                    | Navigable plan and explicit current-versus-future distinction                              |
| 2. Complete lifecycle        | Outer async actions, drain deadline, force-stop, durable operator intent and rollback consistency                        | Meaningful CPU/state/operation tests plus affected lifecycle integration                   |
| 3. Narrow runtime/deployment | Managed/single-shot support, remove retired paths and unused bundled images, consolidate host/instance/client deployment | Package and Compose checks, Docker ownership/isolation and retained API contracts          |
| 4. Complete network client   | Unmodified-node read-only discovery, explicit overrides and safe replica selection; optional signer                      | Discovery/error fixtures and explicit client/signer integration                            |
| 5. Synchronize and validate  | Canonical guides, migration procedure and dated evidence                                                                 | Applicable CPU, Docker, GPU and paid acceptance tiers; pending hardware clearly identified |

Separate behavior changes from mechanical file moves in reviewable local commits.
No push, publication or remote deployment follows merely from recording this plan.

## Acceptance criteria and unresolved dependencies

The broader proposal required five distinct validation tiers:

1. CPU/configuration/documentation checks and package entry-point installation.
2. Docker lifecycle, owned-resource recovery, proxy restrictions and network
   isolation, with no effect on unrelated workloads.
3. A decoded real video from every shipped GPU profile, with pinned image and
   weight inputs, plus relevant switch/stop/restart/rollback checks.
4. Actual multi-GPU concurrent instances, same-model replicas, exclusive
   assignment and failure isolation. No suitable multi-GPU test host was supplied;
   this remains pending rather than inferred from mocks or one GPU.
5. Supported `livepeer/node` signer/orchestrator paid end-to-end videos, including
   network discovery and explicit overrides. Payment integration and final
   settlement are separate evidence claims.

Existing [validation evidence](../../validation/index.md) includes videos from all
three default engines on one RTX 5090, switching, selected recovery cases and
external-volume/offline reuse. It does not establish the complete proposed
contract. The subsequent node report below adds paid single-shot evidence;
paid persistent delivery, settlement, multi-GPU and long-duration behavior remain
pending.

Still to resolve before implementing the broader plan:

- Numeric drain defaults and justified startup/rollback deadlines.
- Exact outer management API/CLI shapes and any persisted-state migration.
- Final host/instance configuration and shared-proxy migration details.
- Safe client capacity/failover behavior around SDK acceptance boundaries.
- Multi-GPU hardware access and an explicitly authorized paid test budget/setup.
- Reapproval of feature retirements in light of the operator's scope correction.

Subsequent operator verification on October 16 passed paid single-shot SSE for all three default engines through the unmodified node signer and direct LAN HTTP; see the [dated report](../../validation/reports/node-paid-validation-2026-10-16.md). Paid persistent delivery and settlement remain pending. This evidence does not resume the deferred platform plan.

## V2 boundary

Two requirements were explicitly deferred to v2: one engine instance spanning
multiple GPUs, and waiting queues. Do not infer agreement to additional v2 work.

## Data, deployment and commit constraints

- Preserve existing wallet/model/cache volumes, host keys and all
  `~/.livepeer/keys/` files. Never copy credentials into the repository or plans.
- On shared Docker hosts, mutate only verified owned resources. Never prune the
  daemon or clean up unrelated workloads.
- Keep ignored operator/editor files intact. Removing compatibility aliases is
  not permission to remove their protected data or an independently used target.
- Never automatically retry a generation with an unknown outcome.
- No automatic SSH deployment, GPU inference, funded requests, recurring
  automation, push or publication as a consequence of this document.
- Follow the current user-approved implementation/commit scope. Historical
  approval of a broader phase is superseded by the narrower current request.

## Decision log

| Date       | Decision                                                              | Consequence                                                                   |
| ---------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 2026-10-16 | Preserve the complete broader discussion in a versioned document      | Future work need not reconstruct requirements from chat                       |
| 2026-10-16 | Operator identified the broader plan as exceeding the desired cleanup | Defer runtime narrowing, new lifecycle semantics and client discovery changes |
| 2026-10-16 | Propose compatibility and Compose cleanup separately                  | Review the smaller scope before implementation; retain current features       |
