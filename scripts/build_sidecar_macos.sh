#!/usr/bin/env bash
set -euo pipefail

# Build the Python API sidecar expected by Tauri on macOS.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$ROOT/scripts/install_exiftool_macos.sh"
FOLDER_MANAGE="$ROOT/folder_manage"
BIN_DIR="$ROOT/src-tauri/bin"
TARGET_TRIPLE="${TARGET_TRIPLE:-$(rustc -vV | awk '/host:/ { print $2 }')}"

if [[ "$TARGET_TRIPLE" != *"apple-darwin"* ]]; then
  echo "Expected a macOS target triple, got: $TARGET_TRIPLE" >&2
  exit 1
fi

mkdir -p "$BIN_DIR"

pushd "$FOLDER_MANAGE" >/dev/null
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
# 用 spec 打包：絕對 pathex + 自動掃描頂層模組，跨平台一致，新增模組免維護。
pyinstaller --clean --noconfirm api-server.spec

# 診斷：列出 PyInstaller 對後端本地模組的缺漏警告（若 sidecar 仍缺模組，CI log 可直接看到）。
WARN_FILE="$FOLDER_MANAGE/build/api-server/warn-api-server.txt"
if [[ -f "$WARN_FILE" ]]; then
  echo "==== PyInstaller missing-module check (local backend modules) ===="
  if grep -E "^missing module named '(tag_index_store|app_paths|exiftool_session|media_path_filters|people_data_store|media_keyword_service|folder_tags_migration)'" "$WARN_FILE"; then
    echo "ERROR: a required backend module was not bundled (see above)." >&2
    popd >/dev/null
    exit 1
  fi
  echo "(no missing local backend modules)"
fi
popd >/dev/null

EXIFTOOL_DEST="$BIN_DIR/exiftool"
if [[ ! -x "$EXIFTOOL_DEST/exiftool" ]]; then
  echo "ExifTool not found at $EXIFTOOL_DEST after install_exiftool_macos.sh" >&2
  exit 1
fi

BUILT="$FOLDER_MANAGE/dist/api-server"
DEST="$BIN_DIR/api-server-$TARGET_TRIPLE"

if [[ ! -f "$BUILT" ]]; then
  echo "api-server not found after PyInstaller build: $BUILT" >&2
  exit 1
fi

cp "$BUILT" "$DEST"
chmod +x "$DEST"
echo "Sidecar copied to $DEST"
