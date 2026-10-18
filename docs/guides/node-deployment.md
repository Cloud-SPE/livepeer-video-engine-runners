# livepeer/node orchestrator, remote signer and Python client

The supported architecture uses **livepeer/node** for both node roles:

| Component          | Runs as                                  | Responsibility                                                                           |
| ------------------ | ---------------------------------------- | ---------------------------------------------------------------------------------------- |
| Orchestrator       | `livepeer orchestrator`                  | Registers runners, advertises apps, proxies requests, meters work and processes payments |
| Remote signer      | `livepeer signer`                        | Holds the payer key, provides discovery and signs payments                               |
| Application client | `video-client`, using `livepeer-gateway` | Uses signer discovery/payments and calls the runner through the orchestrator             |
| GPU runner         | `video-runner`                           | Adapts engine jobs to SSE/trickle and enforces GPU admission                             |

The two node roles can use the same image, in separate processes on different machines. The Python package's name does not imply a separate gateway server. This setup needs no traditional go-livepeer gateway or go-livepeer orchestrator.

The Compose files build node from commit `08081dbda0f4f7b56e362e3af4b6965bfa1b73a4`. If overriding `LIVEPEER_NODE_SOURCE`, use the same source for both roles. These instructions follow the pinned [orchestrator](https://github.com/livepeer/node/blob/08081dbda0f4f7b56e362e3af4b6965bfa1b73a4/docs/orchestrator.md), [signer](https://github.com/livepeer/node/blob/08081dbda0f4f7b56e362e3af4b6965bfa1b73a4/docs/signer.md) and [configuration](https://github.com/livepeer/node/blob/08081dbda0f4f7b56e362e3af4b6965bfa1b73a4/docs/configuration.md) documentation.

## Choose one orchestrator

[Production Compose](../../compose.prod.yml) starts no orchestrator; it connects to the operator's existing node. [Development Compose](../../compose.dev.yml) includes one free offchain orchestrator and requires no signer or funded account. See the [deployment guide](container-deployment.md) for startup and persistence.

For an existing private node, select `compose.prod.yml` and configure its URLs and registration secret. For same-host Docker connectivity, also select `deploy/compose/ingress.yml`; this attaches only the runner and publishes no runner generation port. Choosing the file controls topology; `USE_EXISTING_ORCHESTRATOR` is retained in generated env settings for recovery-tool selection and does not activate an overlay automatically.

For a shared Docker network, reserve an unused address in that network's subnet:

```dotenv
USE_EXISTING_ORCHESTRATOR=1
EXISTING_ORCHESTRATOR_NETWORK=orchestrator-net
EXISTING_RUNNER_IP=172.30.100.60
ORCHESTRATOR_URL=http://orchestrator:8935
RUNNER_URL=http://172.30.100.60:8989
BOOTSTRAP_SECRET=the-existing-node-bootstrap-secret
```

The network name, node DNS name and IP are examples, not automatic allocations. Choose an existing private Docker network and reserve an unused address in its actual subnet. Configure the node's `RunnerGrants` / `--runner-grants` with **that literal IP and port**, for example `172.30.100.60:8989`; node grants do not accept DNS names. The overlay pins the address so grants remain valid after runner recreation. The alias `<COMPOSE_PROJECT_NAME>-runner` also exists, but advertising the reserved literal IP avoids a container-DNS dependency in the request path.

The node's `ServiceURL` must be reachable by clients. `RunnerServiceURL` must be reachable by the runner for heartbeat, callbacks and trickle. For example, clients can use a private LAN/VPN host URL while runners use Docker DNS. Only the runner joins the selected existing network; controller, socket proxy and GPU engine stay on their separate networks. Admin is published only on host loopback, but peers on the runner's Docker networks can reach its container port. Use a private network and an independent admin token.

Paid node configuration requires an on-chain network, orchestrator account/secret files, RPC access, ticket parameters, price conversion and durable redemption state. Use the pinned upstream configuration guide. Existing geth keystores can be selected with `KeystoreFile`; configuration flags and payment databases are not interchangeable with the legacy binary. This repository does not migrate or modify an existing wallet volume.

Set positive `price_usd_per_hour` values in an operator-owned public catalog and select it with `PUBLIC_MODEL_CATALOG`. Repository catalogs default to zero for free testing. Keep model IDs and launch settings aligned with the controller's separately trusted catalog. Drain work and recreate the runner after changing the public catalog; an edited JSON file does not update in-memory prices automatically.

## Optional client-side remote signer

[`deploy/compose/signer.yml`](../../deploy/compose/signer.yml) starts only the **node signer**. It builds the same pinned node source as the orchestrator. It uses Linux host networking, binds API/metrics to loopback, and mounts individual existing key/password/RPC files read-only. It does not copy keys to the GPU host or create/import accounts.

Copy [`deploy/templates/signer.example.toml`](../../deploy/templates/signer.example.toml) into your private settings directory. Review `Orchestrators`, its IP-only `DiscoveryGrants` and USD rate ceilings. The example uses a direct private LAN/VPN orchestrator URL, `http://192.0.2.10:8935`, with the matching literal-IP grant. This is a documentation-only address; replace both entries with your reachable private orchestrator address. Set the node's advertised `ServiceURL` to that client-reachable address and use a Docker/private URL for `RunnerServiceURL` if needed. Direct LAN/VPN routing requires no SSH tunnel. Limits are rates, not cumulative spending budgets. `Orchestrators` is an explicit discovery-source list; this pinned signer does not automatically enumerate orchestrators from the chain.

Prepare a writable signer state directory owned by the same UID/GID as the existing key files. Keystore, password and RPC files must be regular owner-only files (`0400` or `0600`); do not change existing protected keys as part of testing. Secret files contain exact bytes: an unintended trailing newline in a password or RPC URL changes its value.

Set `SIGNER_ENV="$HOME/.config/livepeer-video/signer.env"` in your shell and create that private file with mode `0600`. Replace the example absolute paths below and use the key owner's container-visible UID/GID:

```dotenv
SIGNER_UID=1000
SIGNER_GID=1000
SIGNER_CONFIG_FILE=/absolute/path/to/signer.toml
SIGNER_KEYSTORE_FILE=/absolute/path/to/payer-keystore.json
SIGNER_PASSWORD_FILE=/absolute/path/to/payer-password
SIGNER_RPC_URL_FILE=/absolute/path/to/rpc-url
SIGNER_STATE_DIR=/absolute/path/to/signer-state
```

On rootful Docker, the example UID/GID normally matches the host key owner. Rootless Docker can map that host owner to container UID/GID `0:0`. Use the mapping visible inside the container, keep the key mounts read-only, and do not change protected host keys to accommodate the container.

The node reads password files as exact bytes. Legacy password files with an added line ending may fail decryption. Stage a private `0600` copy outside the checkout containing the actual password bytes and point the signer at that copy; preserve the original file. Likewise, stage protected orchestrator files privately if their original permissions are unsuitable. No password or RPC credential belongs in this repository.

The state directory and all files must already exist; Compose refuses to create missing bind sources. The signer needs the payer's existing funded Livepeer deposit/reserve. Consult upstream instructions for account funding; this Compose file performs no funding or approval transaction.

```sh
docker compose --project-directory . --env-file "$SIGNER_ENV" -f deploy/compose/signer.yml config -q
docker compose --project-directory . --env-file "$SIGNER_ENV" -f deploy/compose/signer.yml build signer
docker compose --project-directory . --env-file "$SIGNER_ENV" -f deploy/compose/signer.yml up -d
curl --fail http://127.0.0.1:8938/readyz
curl --fail http://127.0.0.1:8937/discover-orchestrators
```

`SIGNER_PORT` and `SIGNER_METRICS_PORT` optionally override the default loopback ports 8937 and 8938. Validate Compose with `config -q` to avoid printing interpolated private values.

## Python calls

The SDK calls the signer for discovery/payment signing, then sends application requests and trickle traffic through the orchestrator. It needs routes to both services. With the signer running locally:

```sh
uv run video-client --discovery http://127.0.0.1:8937/discover-orchestrators \
  --signer http://127.0.0.1:8937 \
  --model sglang-fastwan2.1-t2v-1.3b --output fox
uv run video-client --discovery http://127.0.0.1:8937/discover-orchestrators \
  --signer http://127.0.0.1:8937 \
  --model sglang-fastwan2.1-t2v-1.3b --mode persistent --clips 2 --output fox-session
```

These model IDs require the combined `all` catalog. `src/video_runners/tools/validate_gpu.py` and `validate_all.py` also accept `--signer` and `--discovery`. The combined validator waits for discovery after switches before submitting work; it does not retry a failed generation. Persistent reservations bill until released, including idle time. The fault-injection harness targets the free offchain test node and rejects priced discovery.

If the orchestrator is remote and private, an SSH forward can expose its loopback-only client port locally. The reusable [`tunnel service template`](../../deploy/templates/livepeer-video-tunnel.service) forwards orchestrator and admin ports using a private `~/.config/livepeer-video/tunnel.env` containing `ORCHESTRATOR_SSH_HOST`, `LOCAL_ORCHESTRATOR_PORT`, `REMOTE_ORCHESTRATOR_PORT`, `LOCAL_ADMIN_PORT` and `REMOTE_ADMIN_PORT`. It is an optional template, not an installed service. For example, forward ports 8935 and 8990 and configure `ServiceURL`/signer discovery accordingly.

## Payment acceptance and settlement

Test both delivery modes for each selected model with `--signer`; a free-node
pass does not validate payments. Confirm that positive advertised pricing causes
payment challenges, that the SDK obtains signed payments, and that every returned
MP4 decodes completely. HTTP counts are neither ticket counts nor final charges.
Use test rates separately from the production tariff.

The pinned node stores winning tickets durably and redeems them after their
parameter acceptance window ends. A mined transaction still requires canonical
finalized confirmation. With the actual container and database path from your
node configuration, inspect recorded redemption attempts:

```sh
docker exec "$ORCHESTRATOR_CONTAINER" livepeer orchestrator redemptions \
  --config "" --redeemer-db "$REDEEMER_DB"
```

This command reports attempt hashes/phases/errors. An empty array does not prove
there are no queued winning tickets. Inspect the recipient database's
`winning_tickets` table read-only and count rows with `redeemed_at IS NULL` before
removing temporary payment state. Never publish signatures, randomness or raw
signed transactions from that database. Do not add retry/submission flags merely
to make a pending result complete.

For settlement evidence, record the successful transaction receipt, verify its
block hash still matches the canonical block, and verify its block number is at
or below the RPC's `finalized` head. Confirm the node has marked the corresponding
tickets redeemed. Chain finality can lag delivery substantially; a successful
video, signed batch or pending/submitted transaction proves a different step.
You can stop the GPU runner after delivery while keeping the CPU node and its
durable state available for redemption. Check pending liabilities before stopping
that node or removing its state.

## Validation status and cleanup

Free node orchestration, all three default GPU models and selected recovery cases have been tested. Signer Compose configuration and CLI options are checked against the pinned node source/image. **Paid single-shot SSE and two-clip persistent delivery passed for all three default engines through a local node signer and direct private LAN HTTP on October 18.** See the [acceptance report](../validation/reports/operator-acceptance-2026-10-18.md#paid-delivery-and-settlement) for payment evidence and its separate settlement status. The [October 16 report](../validation/reports/node-paid-validation-2026-10-16.md) records earlier paid SSE checks. The [historical paid report](../validation/reports/paid-validation-2026-10-15.md) used legacy go-livepeer and does not prove that replacement path.

Dated reports record completed tests and their cleanup; they do not identify a currently running service. For a new run, stop the provider using the documented [shutdown sequence](container-deployment.md#stop-restart-and-update), then stop any test-only node and signer projects with their original Compose/env selections. Preserve existing wallets, keys, model/cache volumes and durable payment/accounting state. Inspect pending redemptions and accounting before deleting any owned temporary state. Remove only verified test resources; never prune a shared daemon.
