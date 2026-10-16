#!/usr/bin/env bash
# End-to-end check against a running stub stack:
#
#   ENGINE=stub docker compose -f compose.dev.yml up -d --build --wait
#   tests/e2e/e2e.sh
#
# Covers discovery, single-shot (SSE), a persistent session with several clips,
# the admin token, and a model switch across both engine API flavours.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/../.."
ADMIN_URL=${ADMIN_URL:-http://127.0.0.1:8990}
ADMIN_TOKEN=${RUNNER_ADMIN_TOKEN:-change-me}
FIRST_MODEL=${E2E_MODEL_ONE:-stub-wan-t2v}
SECOND_MODEL=${E2E_MODEL_TWO:-stub-h3}
if [ -n "${CPU_ARTIFACT_DIR:-}" ]; then
  out=$CPU_ARTIFACT_DIR
  mkdir -p "$out"
else
  out=$(mktemp -d)
  trap 'rm -rf "$out"' EXIT
fi

client() { uv run --quiet video-client --discovery "${DISCOVERY_URL:-http://localhost:8935/discovery}" "$@"; }
step() { printf '\n== %s\n' "$*"; }
fail() {
  echo "FAIL: $*" >&2
  exit 1
}

step "wait for both registrations"
for _ in $(seq 60); do
  apps=$(client --list 2>/dev/null || true)
  grep -Fq "video:sessions/$FIRST_MODEL " <<<"$apps" && break
  sleep 2
done
echo "$apps"
grep -Fq "video:generations/$FIRST_MODEL " <<<"$apps" || fail "single-shot app not listed"
grep -Fq "video:sessions/$FIRST_MODEL " <<<"$apps" || fail "persistent app not listed"

step "single-shot"
client --model "$FIRST_MODEL" --output "$out/single"
test -s "$out/single.mp4" || fail "no single-shot clip"

step "persistent, 3 clips in one session"
client --model "$FIRST_MODEL" --mode persistent --clips 3 --output "$out/session"
for i in 000 001 002; do
  test -s "$out/session-$i.mp4" || fail "missing persistent clip $i"
done

step "admin rejects a missing token"
code=$(curl -s -o /dev/null -w '%{http_code}' "$ADMIN_URL/admin/status")
[ "$code" = 401 ] || fail "admin status without token returned $code"

step "switch to $SECOND_MODEL"
curl -fsS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$ADMIN_URL/admin/model" -d "{\"model\":\"$SECOND_MODEL\"}"
echo
client --list | tee "$out/apps"
grep -Fq "video:generations/$SECOND_MODEL " "$out/apps" || fail "switched app not listed"
grep -Fq "video:generations/$FIRST_MODEL " "$out/apps" && fail "previous model still listed"
client --model "$SECOND_MODEL" --output "$out/second"
client --model "$SECOND_MODEL" --mode persistent --clips 2 --output "$out/second"
test -s "$out/second.mp4" -a -s "$out/second-001.mp4" || fail "no clips from $SECOND_MODEL"

step "switch back"
curl -fsS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$ADMIN_URL/admin/model" -d "{\"model\":\"$FIRST_MODEL\"}"
echo

printf '\nPASS\n'
