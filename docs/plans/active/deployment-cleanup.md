# Focused compatibility and Compose cleanup

Recorded: 2026-10-16. Status: **completed on 2026-10-16**.

The operator's immediate request is to remove compatibility clutter, simplify
Compose and provide clear production and development stacks. The
[broader provider plan](../deferred/provider-platform-v1.md) records the preceding
discussion but is deferred. It must not expand the scope of this cleanup.

This document records the approved scope and its execution. Operating instructions live in the
[container guide](../../guides/container-deployment.md).

## Objective

A contributor or operator should be able to choose production or development,
provide the documented settings and start the appropriate stack without
discovering a matrix of compatibility aliases and engine-specific overlays.

Achieve this through path cleanup, Compose consolidation and synchronized
instructions. Preserve existing application and lifecycle behavior.

## Scope boundary

| Include now                                                                      | Defer                                                                                   |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Remove tracked symlinks and root Python compatibility facades                    | Retiring bundled or external lifecycle support                                          |
| Update imports, mounts, scripts, package commands and CI to canonical paths      | Retiring persistent sessions or waiting mode                                            |
| Clear production and complete development Compose entry points                   | New force-stop, drain-timeout or async outer-management semantics                       |
| Consolidate redundant overlays and make engine selection configuration-driven    | Changing restart intent, rollback behavior or controller state schemas                  |
| Small nonsecret env examples and explicit initialization/preparation commands    | Network-first discovery and new client replica/failover behavior                        |
| Keep existing preparation, optional signer and advanced lifecycle recipes usable | Shared host-wide socket-proxy infrastructure or a new controller/scheduler              |
| Current docs and appropriate checks for the changed paths/configuration          | A new deployment renderer, host/instance configuration system or broad runtime refactor |

Keep model IDs, generation/session routes, event shapes, catalog schemas, prices,
existing image/weight pins and runtime CLI flags/defaults. Changing Compose
entry-point names and removing duplicate compatibility commands is the intended
breaking change; document the migration explicitly.

The default production recipe can select the existing managed mode without
removing the bundled/external implementations. Choosing a recommended deployment
is separate from narrowing what the runtime supports.

## Recommended everyday stacks

### Production

One real root file, `compose.prod.yml`:

- Existing CPU runner, controller and socket proxy.
- Existing separate GPU engine container created by the controller.
- Connect to an operator's existing `livepeer/node` orchestrator.
- No demo orchestrator, signer or test engine starts implicitly.
- Select the current per-engine or combined catalog, model, reserved GPU UUID,
  private connectivity and existing external volume names through configuration.
- Preserve the current authenticated/private control and Docker API boundaries.
- Keep one proxy per managed deployment for now; sharing proxies across instances
  is a separate topology change.

Starting another instance uses the existing independent project identity, GPU,
ports/subnets and state settings. Do not introduce a host scheduler or use
`--scale` to pretend one configured GPU unit is several independent instances.

### Development

One real root file, `compose.dev.yml`:

- Bring up the pinned local `livepeer/node` orchestrator, runner, controller and
  socket proxy, plus a controller-managed CPU stub engine by default.
- Provide the pieces needed to exercise registration, discovery, generation,
  switching and recovery without GPU hardware, keys or payment.
- Build local application sources using the existing Docker targets.
- Allow explicitly selecting the existing real GPU profiles on a suitable host,
  with prepared images/weights and an assigned GPU. Stub is the credential-free
  default, not a claim that real engines can run without GPUs.
- Offer the existing optional signer and a documented client command for paid
  validation. Paid mode requires explicit private configuration and is not part
  of the default free developer startup.
- Run the existing Python client from the development environment and save
  outputs locally. Do not create another gateway service.

Local Python-only development and `scripts/check.sh` remain available separately;
Docker is not required for routine unit/contract checks.

### Small supporting recipes

Two everyday entry points do not require cramming unrelated services into them.
Retain clearly named real support files only where they have a distinct purpose:

- Explicit asset preparation into existing external volumes.
- Optional client-side signer, which may run on a different machine and requires
  private files. Reuse its service in developer workflows rather than making keys
  a requirement of the free stack.
- A private-network attachment overlay if both current connectivity variants
  cannot be expressed clearly in the production file. Preserve same-host Docker
  networking and private LAN/VPN access; do not drop one to meet a file-count goal.
- Bundled/external examples or recipes needed to retain existing lifecycle
  functionality. Consolidate engine-specific differences into ordinary settings
  where practical; do not silently remove their functionality.

Use ordinary Docker Compose features. Prefer two readable files and a small
amount of explicit repeated configuration over a new web of base files,
templates or generated YAML. Any sharing should be shallow and inspectable with
`docker compose config`; no replacement compatibility aliases.

Docker documents both [service reuse](https://docs.docker.com/compose/how-tos/multiple-compose-files/extends/)
and [optional profiles](https://docs.docker.com/compose/how-tos/profiles/). Validate
the actual resolved project before choosing either for a service. Check build and
bind paths, dependencies, network aliases and volume declarations. Optional paid
configuration must not prevent the free stack from resolving or starting.

## Proposed operator experience

After one-time initialization and, for GPUs, explicit image/weight preparation,
the target everyday commands are:

```sh
# After initialization and any required GPU asset preparation.
docker compose --env-file /path/to/prod.env -f compose.prod.yml up -d
docker compose --env-file /path/to/dev.env -f compose.dev.yml up -d --build
```

The corresponding `logs`, `ps` and `down` commands use the same env/project/file
selection. Retain the existing managed shutdown sequence so dynamically created
engine containers are stopped deliberately before removing the control stack;
plain Compose teardown must not be documented as owning those engine containers.

Document one-time initialization, image preparation and weight preparation next
to these commands. Preserve their explicit nature; do not hide long downloads or
daemon mutations inside an innocuous status/config command. A fresh developer
setup still needs the documented initialization; `up` alone is not a promise to
create every external volume or private credential file.

Keep private env files and credential files outside tracked sources. Do not
require the deferred two-level host/instance env system. The existing env format
can be retained and clarified unless a concrete consolidation issue requires a
small, documented migration.

## Compatibility cleanup inventory

The baseline at `9f57ee6` had 27 tracked symlinks:

- Twelve root Compose aliases to `deploy/compose/`.
- The root `docker/` directory alias to `deploy/docker/`.
- Two config/template aliases for signer configuration and the tunnel service.
- The root standalone engine-launcher alias.
- Seven preparation/configuration/validation Python tool aliases, plus the CPU
  harness alias, under `scripts/`.
- Three end-to-end shell aliases under `scripts/`.

It also has root Python forwarding facades for runner, controller, engine,
lifecycle, client and stub implementations. Those are regular files, not symlinks.

Cleanup rules:

1. Keep actual Python implementations under `src/video_runners/`. Use the four
   existing installed runtime commands (`video-runner`, `video-controller`,
   `video-client`, `video-stub-engine`). Add a direct package command only where
   needed to replace a host-tool alias; do not create another forwarding module.
2. Preserve the standard-library-only engine launcher, and update every Docker
   bind/copy reference to its real source path. Upstream engine images must not
   suddenly need the runner package installed.
3. Keep Dockerfiles at their real `deploy/docker/` paths. Removing the directory
   alias does not remove bundled Dockerfiles or change their dependencies.
4. Keep test shell implementations in `tests/e2e/`; update callers directly.
   Keep actual operational shell scripts where they have a job beyond forwarding.
5. Make the two proposed root Compose entry points real canonical files. Update
   all build/bind paths, callers and guides before deleting their previous files.
6. Keep one real signer template. For the real SSH-tunnel `.service` example,
   explain its optional purpose; deleting its alias does not uninstall a service
   or authorize changing a user's systemd configuration. The proposed replacement
   with an on-demand SSH example can be considered separately from runtime work.
7. Update tests that import root facades to import canonical package modules.
   Replace legacy-equivalence checks with meaningful installed-command and
   standalone-launcher checks. Preserve behavior assertions.
8. Search current source, Dockerfiles, scripts, CI and operating documentation
   for retired names. Historical execution/validation records remain historical;
   label old commands where needed instead of rewriting recorded evidence.

No feature deletion should be justified merely by a file being inconvenient to
move. If consolidation exposes a runtime defect, record it separately rather
than expanding this cleanup into the deferred platform plan.

## Implementation sequence

1. **Agree on this scope and entry-point behavior.** Approved by the operator on
   2026-10-16; the preceding documentation-only turn changed no implementation.
2. **Remove aliases mechanically.** Migrate callers/imports/mounts, preserve
   implementations and verify installed/standalone commands. Keep the diff
   separate from Compose topology changes.
3. **Consolidate Compose.** Produce the production and development entry points,
   preserve required advanced recipes, and simplify the existing deployment
   wrapper or remove it if direct Compose commands replace all of its selection
   work. Keep initialization/preparation responsibilities explicit.
4. **Synchronize instructions and verification.** Update README, architecture,
   layout/deployment/node guides, command references and CI to canonical paths.
   Add a short old-to-new command migration table, not compatibility wrappers.
5. **Review the result.** Report actual remaining files and their purposes,
   checks performed and any behavior difference requiring separate approval.

Do not move unrelated package modules or combine formatting churn with the
mechanical migration. Follow current commit instructions; no push or publication.

## Acceptance and verification

- No tracked symlinks or root runtime forwarding facades remain after the cleanup.
- Production configuration starts no demo node, signer or CPU fixture implicitly.
- Default developer configuration resolves and runs without keys, GPU or model
  downloads, after documented initialization.
- Existing runtime modes, delivery contracts and management semantics remain
  covered. Real GPU engine profiles continue to resolve without editing YAML for
  every engine choice.
- Same-host/private-LAN connectivity remains documented and configuration-tested.
- External model/cache/wallet volume names and stored contents remain unchanged.
- Fast checks, formatting, wheel/CLI checks and the affected Compose resolution
  matrix pass. Use placeholder credentials and quiet config validation, not
  printed private configuration.
- Run affected isolated Docker CPU integration for registration, decoded fixture
  video, both delivery modes, switching/recovery and proxy/network isolation.
  Remove only resources whose ownership is verified by the existing harness.
- No new tests solely asserting arbitrary file layouts. Existing checker,
  packaging, contract and integration checks should establish the changed paths
  and behavior.
- GPU and funded validation are separate operator actions. A Compose/path cleanup
  does not require implementing the broader hardware/payment acceptance plan.
  If it changes actual engine launch semantics, run the applicable hardware tier
  before claiming that change validated; do not broaden old evidence.

## Protected resources and exclusions

Preserve existing wallet/model/cache volumes, all `~/.livepeer/keys/`, host
keys, ignored operator/editor files and unrelated workloads. Do not copy secrets
into the repository, prune Docker, remove external volumes, deploy to SSH hosts,
submit funded work, install systemd/recurring automation or push changes as part
of writing/reviewing this proposal.

## Progress

- [x] Inspect current implementation and record the scope correction.
- [x] Preserve the full broader plan as deferred context.
- [x] Write this smaller proposal and link both plans from the documentation map.
- [x] Agree on the focused production/development behavior before implementation.
- [x] Remove compatibility aliases and migrate all callers.
- [x] Consolidate Compose without removing runtime features.
- [x] Synchronize guides, run applicable checks and record the resulting diff.

## Initial documentation-only verification

On 2026-10-16, `scripts/check.sh` passed repository/configuration checks, Black,
Ruff and all 146 CPU tests. Prettier 3.3.3 checks passed for both new plans and
the documentation index; `git diff --check` passed. That initial turn changed only those
three Markdown files. No Compose configuration, runtime code, Docker deployment,
GPU inference or paid operation was changed or exercised. These results validate
the documentation addition, not the proposed deployment files.

## Implementation and verification log

Completed on 2026-10-16 against the worktree based on `9f57ee6`:

- Removed all 27 compatibility symlinks and six root Python forwarding facades.
  The four installed runtime commands remain canonical; host tools and test
  scripts run from their actual package/test paths. Docker entry points and the
  standalone upstream-engine launcher no longer depend on aliases.
- Replaced twelve canonical Compose files with two real root entry points and
  seven support files. Production contains only runner/controller/proxy;
  development adds the pinned free node and a build-only CPU image service that
  completes before controller startup. Bundled/external modes, both delivery
  modes and existing management semantics remain supported.
- Consolidated external per-engine overlays into explicit image settings. The
  initializer selects the existing image reference and writes the chosen UUID
  to `GPU_ID` for the external GPU overlay. Existing env files must set that
  external image explicitly; they are never overwritten.
- Removed the selection wrapper. Initialization, asset preparation, private
  network attachment and optional signing are explicit commands/recipes.
- Updated current guides, examples, architecture, generated command reference,
  CI and contribution instructions. Historical execution/report command text
  remains historical; the migration guide replaces compatibility forwarding.
- `scripts/check.sh` passed repository/configuration checks, Black, Ruff and
  **152 CPU tests**. Additional cases cover external image/GPU selection,
  private-file preservation and external volume initialization.
- **33 Compose configurations** resolved using placeholder settings with no
  daemon access. Resolved-project inspection also verified production service
  membership, developer image-build ordering, private endpoints, ingress removal
  of generation publishing and external-volume preservation.
- A wheel built and installed into a fresh environment; all four runtime commands
  passed outside the checkout. All pre-commit hooks passed, including the new
  untracked files, plus shell syntax and `git diff --check`.
- The host's newer npm rejected pre-commit's local Git dependency bootstrap. An
  isolated task cache and npm 10.9.2 completed the same pinned hooks; no repository
  hook pins, global npm settings or recurring automation were changed.

Actual Docker CPU integration results (worktree-derived run identifiers omitted):

| Run                 | Scope                                                                                                                                              | Decoded fixture videos | Result                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | --------------------------------------- |
| Managed development | Managed development, combined catalog; both delivery modes, model/API switching, controller/runner restart, proxy denials and endpoint isolation   | 9                      | Passed; owned-resource cleanup complete |
| Bundled             | Retained bundled recipe; both delivery modes and model/API switching                                                                               | 7                      | Passed; owned-resource cleanup complete |
| External            | Retained external recipe with local node; both delivery modes and HTTP 409 on model switch                                                         | 2                      | Passed; owned-resource cleanup complete |
| Production          | Production provider against an already started owned free-node fixture; same delivery, switch/recovery and isolation checks as managed development | 9                      | Passed; owned-resource cleanup complete |

The production probe supplied the test node and CPU image builder only through a
private fixture overlay. The production source file contains no orchestrator or
image-build service. Its builder was build-only, reflecting pre-staged engine
images in production. External-probe volumes were unique owned test volumes, not
operator model volumes.

Two earlier supplemental fixture-startup attempts needed corrections: matching a
preallocated external network name and keeping the production fixture image
builder out of normal startup. Those attempts submitted no generations and their
owned-resource cleanup completed. No generation was automatically replayed.

The **27 videos** are CPU test patterns, not new GPU inference evidence. Temporary
videos, receipts, logs, private fixture inputs, probe scripts and wheel/hook test
directories were removed after inspection and ownership verification. Normal
build/dependency caches and unrelated Docker resources were preserved.

The runner/controller/lifecycle/backend implementations, real-engine public and
trusted catalogs, image/weight manifests, dependency declarations and lock remain
unchanged. Client/backend edits outside tools are comments only. No SSH host,
GPU inference, model download, funded signer, wallet/model volume, existing key,
installed systemd service, push or publication was involved. Existing GPU/paid
validation gaps remain unchanged; see the [validation matrix](../../validation/index.md).

## Subsequent documentation review

The October 16 documentation sweep checked current guides, examples, architecture,
plans and validation summaries against the package commands, Compose definitions,
catalogs and pinned upstream node documentation. It:

- Removed operator hostnames, actual addresses, private resource names and
  worktree-derived validation IDs from public files. Technical model/image/GPU
  inputs, measurements and output hashes remain as validation evidence.
- Made production/client instructions generic, with labeled documentation-only
  host addresses and example Docker networks, paths and grants.
- Added the canonical image-name/role table and clarified managed versus bundled
  packaging, CLI defaults, discovery adapter metadata and configured signer
  discovery sources.
- Corrected stale command labels and paid-validation status. Earlier plans are
  explicitly historical or deferred; they do not override current code/guides.
- Added privacy guidance for future docs, reports, issue forms and pull requests;
  renamed an operator-specific wallet test fixture to a generic fixture name.

Fast checks passed with **152 CPU tests**, the **33 Compose configurations**
resolved, and **12 runtime/tool entry points** passed `--help`. Markdown/YAML
formatting, local links/anchors, generated-reference consistency and identifier
scans passed. No service deployment, GPU inference or credential access ran as
part of this review. It covers current file contents; earlier Git revisions
were not rewritten.
