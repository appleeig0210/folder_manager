#!/usr/bin/env bash
set -euo pipefail

# Generate a minimal macOS .icns from the shared Tauri icon.
# Run this on macOS because it uses the system `sips` and `iconutil` tools.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ICONS_DIR="$ROOT/src-tauri/icons"
SOURCE_PNG="$ICONS_DIR/icon.png"
ICONSET="$ICONS_DIR/icon.iconset"
ICNS="$ICONS_DIR/icon.icns"

mkdir -p "$ICONS_DIR"

if [[ ! -f "$SOURCE_PNG" ]]; then
  echo "Missing $SOURCE_PNG. Create a 1024x1024 PNG first." >&2
  exit 1
fi

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

sips -z 16 16 "$SOURCE_PNG" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32 "$SOURCE_PNG" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$SOURCE_PNG" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64 "$SOURCE_PNG" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$SOURCE_PNG" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256 "$SOURCE_PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$SOURCE_PNG" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512 "$SOURCE_PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$SOURCE_PNG" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$SOURCE_PNG" --out "$ICONSET/icon_512x512@2x.png" >/dev/null

iconutil -c icns "$ICONSET" -o "$ICNS"
rm -rf "$ICONSET"
echo "Generated $ICNS"
