#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$ROOT/src-tauri/bin"

SIDECAR="$(find "$BIN_DIR" -maxdepth 1 -type f -name 'api-server-*' -perm +111 2>/dev/null | head -n 1 || true)"

if [[ -z "$SIDECAR" ]]; then
  SIDECAR="$(find "$BIN_DIR" -maxdepth 1 -type f -name 'api-server-*' 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "$SIDECAR" ]]; then
  echo "Sidecar binary not found under $BIN_DIR" >&2
  exit 1
fi

echo "Verifying ffmpeg in sidecar: $SIDECAR"
"$SIDECAR" --verify-ffmpeg
