#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$ROOT/src-tauri/bin/exiftool"
VERSION="13.59"
TMP_DIR="$(mktemp -d)"
ARCHIVE="$TMP_DIR/Image-ExifTool-$VERSION.tar.gz"
URL="https://sourceforge.net/projects/exiftool/files/Image-ExifTool-$VERSION.tar.gz/download"

mkdir -p "$DEST_DIR"

echo "Downloading ExifTool $VERSION..."
curl -fsSL "$URL" -o "$ARCHIVE"
tar -xzf "$ARCHIVE" -C "$TMP_DIR"

SRC_DIR="$TMP_DIR/Image-ExifTool-$VERSION"
cp "$SRC_DIR/exiftool" "$DEST_DIR/exiftool"
chmod +x "$DEST_DIR/exiftool"
cp -R "$SRC_DIR/lib" "$DEST_DIR/"

echo "ExifTool installed to $DEST_DIR"
