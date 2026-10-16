#!/usr/bin/env bash
# Resolve deployment choices without a daemon, GPU or private settings.
set -euo pipefail
if [ "${VIDEO_CONFIG_ISOLATED:-}" != 1 ]; then
  exec env -i PATH="$PATH" HOME="$HOME" VIDEO_CONFIG_ISOLATED=1 bash "$0"
fi
cd "$(dirname "$0")/../.."
export BOOTSTRAP_SECRET=config-placeholder
export RUNNER_ADMIN_TOKEN=config-placeholder-admin
export ENGINE_CONTROLLER_TOKEN=config-placeholder-at-least-32-characters
export ORCHESTRATOR_URL=http://10.20.0.5:8935
export RUNNER_URL=http://10.20.0.6:8989
export RUNNER_BIND_HOST=10.20.0.6
export ENGINE_GPU_UUID=GPU-config-test
export LIGHTX2V_ENGINE_IMAGE=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export EXISTING_ORCHESTRATOR_NETWORK=ingress
export EXISTING_RUNNER_IP=172.18.0.60
count=0
dc() {
  docker compose --project-directory "$PWD" --env-file /dev/null "$@" config -q
  count=$((count + 1))
}
for engine in stub sglang lightx2v vllm-omni all; do
  export ENGINE=$engine
  dc -f compose.prod.yml
  dc -f compose.dev.yml
  dc -f compose.prod.yml -f deploy/compose/ingress.yml
done
for engine in stub sglang lightx2v vllm-omni; do
  export ENGINE=$engine EXTERNAL_ENGINE_IMAGE=test-engine:local
  if [ "$engine" = stub ]; then
    dc -f deploy/compose/bundled.yml
    dc -f deploy/compose/external.yml
  else
    dc -f deploy/compose/bundled.yml -f deploy/compose/gpu.yml
    dc -f deploy/compose/external.yml -f deploy/compose/engine-gpu.yml
  fi
  dc -f deploy/compose/external.yml --profile local-orchestrator
  dc -f deploy/compose/external.yml -f deploy/compose/ingress.yml
done
dc -f deploy/compose/assets.yml
export SIGNER_UID=1000 SIGNER_GID=1000
export SIGNER_CONFIG_FILE=/tmp/signer.toml SIGNER_KEYSTORE_FILE=/tmp/key.json
export SIGNER_PASSWORD_FILE=/tmp/key.password SIGNER_RPC_URL_FILE=/tmp/rpc-url
export SIGNER_STATE_DIR=/tmp/signer-state
dc -f deploy/compose/signer.yml
printf '%s Compose configurations resolved\n' "$count"
