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
pyinstaller \
  --onefile \
  --name api-server \
  --paths . \
  api/main.py \
  --hidden-import=api.deps \
  --hidden-import=api.routes.config \
  --hidden-import=api.routes.tree \
  --hidden-import=api.routes.preview \
  --hidden-import=api.routes.thumbnails \
  --hidden-import=api.routes.tags \
  --hidden-import=api.routes.files \
  --hidden-import=media_keyword_service \
  --hidden-import=folder_tags_migration \
  --hidden-import=tag_index_store \
  --hidden-import=app_paths \
  --hidden-import=exiftool_session \
  --hidden-import=media_path_filters \
  --hidden-import=people_data_store \
  --collect-submodules=uvicorn
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
