from __future__ import annotations

from pathlib import Path


def is_junk_filename(name: str) -> bool:
    """macOS AppleDouble sidecar (._*) and Finder metadata (.DS_Store)."""
    return name == ".DS_Store" or name.startswith("._")


def is_junk_path(path: Path) -> bool:
    return is_junk_filename(path.name)
