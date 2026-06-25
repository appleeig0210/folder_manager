#!/usr/bin/env bash
set -euo pipefail

# Start a built api-server sidecar and verify /api/health responds.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_TRIPLE="${TARGET_TRIPLE:-$(rustc -vV | awk '/host:/ { print $2 }')}"
SIDECAR="${1:-$ROOT/src-tauri/bin/api-server-$TARGET_TRIPLE}"
PORT="${API_PORT:-8765}"
LOG_FILE="$(mktemp -t api-server-smoke.XXXXXX.log)"

cleanup() {
  if [[ -n "${SIDECAR_PID:-}" ]] && kill -0 "$SIDECAR_PID" 2>/dev/null; then
    kill "$SIDECAR_PID" 2>/dev/null || true
    wait "$SIDECAR_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ ! -f "$SIDECAR" ]]; then
  echo "Sidecar not found: $SIDECAR" >&2
  exit 1
fi

chmod +x "$SIDECAR"
echo "Smoke testing sidecar: $SIDECAR"

"$SIDECAR" >"$LOG_FILE" 2>&1 &
SIDECAR_PID=$!

for attempt in $(seq 1 60); do
  if ! kill -0 "$SIDECAR_PID" 2>/dev/null; then
    echo "api-server exited before health check succeeded (attempt $attempt)" >&2
    echo "---- api-server log ----" >&2
    cat "$LOG_FILE" >&2 || true
    exit 1
  fi

  if curl -fsS "http://127.0.0.1:${PORT}/api/health" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    echo "api-server health check passed on attempt $attempt"
    exit 0
  fi

  sleep 1
done

echo "api-server health check timed out after 60s" >&2
echo "---- api-server log ----" >&2
cat "$LOG_FILE" >&2 || true
exit 1
