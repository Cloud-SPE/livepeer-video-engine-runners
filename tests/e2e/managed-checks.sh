#!/usr/bin/env bash
# Workload and isolation checks; cpu_harness.py owns resources and cleanup.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
dc() { docker compose --project-directory "$PWD" --env-file "$TEST_ENV_FILE" -p "$COMPOSE_PROJECT_NAME" -f "${TEST_COMPOSE_FILE:-compose.dev.yml}" -f "$TEST_COMPOSE_OVERLAY" "$@"; }
export ADMIN_URL="http://127.0.0.1:$RUNNER_ADMIN_PORT"
export DISCOVERY_URL="http://127.0.0.1:$ORCHESTRATOR_PORT/discovery"
tests/e2e/e2e.sh
curl -fsS -X POST -H "Authorization: Bearer $RUNNER_ADMIN_TOKEN" "$ADMIN_URL/admin/model" -d "{\"model\":\"$E2E_MODEL_TWO\"}"
# Explicit force also works through the real controller/proxy on CPU fixtures.
curl -fsS -X POST -H "Authorization: Bearer $RUNNER_ADMIN_TOKEN" "$ADMIN_URL/admin/model" -d "{\"model\":\"$E2E_MODEL_TWO\",\"force\":true}"
uv run --quiet python - <<'PY'
import os, urllib.error, urllib.request
url = os.environ['ADMIN_URL'] + '/metrics'
try:
    urllib.request.urlopen(url, timeout=5)
    raise SystemExit('Metrics unexpectedly allowed anonymous access')
except urllib.error.HTTPError as error:
    assert error.code == 401, error
request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + os.environ['RUNNER_ADMIN_TOKEN']})
with urllib.request.urlopen(request, timeout=5) as response:
    text = response.read().decode()
assert 'video_runner_jobs_total' in text
assert 'video_runner_switches_total' in text and 'mode="force"' in text
print('Authenticated metrics and explicit forced switching verified')
PY
dc restart controller
# Generation waits for registrations to recover; retry discovery, not generation.
wait_for_model() {
  for _ in $(seq 60); do
    if uv run --quiet video-client --discovery "$DISCOVERY_URL" --list 2>/dev/null | grep -Fq "video:generations/$E2E_MODEL_TWO "; then return; fi
    sleep 1
  done
  echo 'Model did not recover' >&2
  return 1
}
# Wait for the restart to finish resetting the engine before observing recovery.
sleep 3
wait_for_model
uv run --quiet video-client --discovery "$DISCOVERY_URL" --model "$E2E_MODEL_TWO" --output "$CPU_ARTIFACT_DIR/controller-recovered"
dc restart runner
wait_for_model
uv run --quiet video-client --discovery "$DISCOVERY_URL" --model "$E2E_MODEL_TWO" --output "$CPU_ARTIFACT_DIR/runner-recovered"
# Raw daemon routes remain unavailable even from the controller's network.
dc exec -T controller python - <<'PY'
import urllib.error, urllib.request
for method, path in [('GET','/v1.51/info'),('POST','/v1.51/build'),('POST','/v1.51/containers/'+'a'*64+'/exec')]:
    request = urllib.request.Request('http://socket-proxy:2375'+path, method=method)
    try:
        urllib.request.urlopen(request, timeout=5)
        raise SystemExit('Proxy unexpectedly allowed '+path)
    except urllib.error.HTTPError as error:
        assert error.code == 403, error
print('Proxy blocked unrelated Docker API routes')
PY
# Probe direct IPs as well as relying on Docker DNS/network membership.
proxy_ip=$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(dc ps -q socket-proxy)")
controller_engine_ip=$(docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{if eq $name "'"$ENGINE_NETWORK"'"}}{{$network.IPAddress}}{{end}}{{end}}' "$(dc ps -q controller)")
cat > "$CPU_ARTIFACT_DIR/unreachable.py" <<'PY'
import sys, urllib.error, urllib.request
for url in sys.argv[1:]:
    try:
        urllib.request.urlopen(url, timeout=2)
    except urllib.error.HTTPError:
        raise SystemExit('Unexpected HTTP access to '+url)
    except (urllib.error.URLError, TimeoutError):
        continue
    raise SystemExit('Unexpected access to '+url)
print('Private endpoint isolation verified')
PY
dc exec -T runner python - "http://$proxy_ip:2375/v1.51/containers/json" < "$CPU_ARTIFACT_DIR/unreachable.py"
engine_id=$(docker ps -q --filter "label=io.livepeer.video.owner=$ENGINE_NAMESPACE")
docker exec -i "$engine_id" python - "http://$proxy_ip:2375/v1.51/containers/json" \
  "http://$controller_engine_ip:9200/healthz" "http://$CONTROL_SUBNET_PREFIX.20:9200/healthz" < "$CPU_ARTIFACT_DIR/unreachable.py"
printf '\nManaged engine recovery and proxy checks passed\n'
