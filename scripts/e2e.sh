#!/usr/bin/env bash
# End-to-end check against a running stub stack:
#
#   ENGINE=stub docker compose up -d --build --wait
#   scripts/e2e.sh
#
# Covers discovery, single-shot (SSE), a persistent session with several clips,
# the admin token, and a model switch across both engine API flavours.
set -euo pipefail

cd "$(dirname "$0")/.."
ADMIN_URL=${ADMIN_URL:-http://127.0.0.1:8990}
ADMIN_TOKEN=${RUNNER_ADMIN_TOKEN:-change-me}
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT

client() { uv run --quiet client.py "$@"; }
step() { printf '\n== %s\n' "$*"; }
fail() {
  echo "FAIL: $*" >&2
  exit 1
}

step "wait for both registrations"
for _ in $(seq 60); do
  apps=$(client --list 2>/dev/null || true)
  grep -q "video:sessions/stub-wan-t2v" <<<"$apps" && break
  sleep 2
done
echo "$apps"
grep -q "^video:generations/stub-wan-t2v " <<<"$apps" || fail "single-shot app not listed"
grep -q "^video:sessions/stub-wan-t2v " <<<"$apps" || fail "persistent app not listed"

step "single-shot"
client --output "$out/single"
test -s "$out/single.mp4" || fail "no single-shot clip"

step "persistent, 3 clips in one session"
client --mode persistent --clips 3 --output "$out/session"
for i in 000 001 002; do
  test -s "$out/session-$i.mp4" || fail "missing persistent clip $i"
done

step "admin rejects a missing token"
code=$(curl -s -o /dev/null -w '%{http_code}' "$ADMIN_URL/admin/status")
[ "$code" = 401 ] || fail "admin status without token returned $code"

step "switch to stub-h3 (lightx2v API)"
curl -fsS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$ADMIN_URL/admin/model" -d '{"model": "stub-h3"}'
echo
client --list | tee "$out/apps"
grep -q "^video:generations/stub-h3 " "$out/apps" || fail "switched app not listed"
grep -q "stub-wan-t2v" "$out/apps" && fail "previous model still listed"
client --model stub-h3 --output "$out/h3"
client --model stub-h3 --mode persistent --clips 2 --output "$out/h3"
test -s "$out/h3.mp4" -a -s "$out/h3-001.mp4" || fail "no clips from stub-h3"

step "switch back"
curl -fsS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "$ADMIN_URL/admin/model" -d '{"model": "stub-wan-t2v"}'
echo

printf '\nPASS\n'
