from __future__ import annotations

import os
import sys
from pathlib import Path


def get_app_data_dir(app_name: str) -> Path:
    home = Path.home()

    if sys.platform == "darwin":
        base_dir = home / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base_dir = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
    else:
        base_dir = Path(os.environ.get("XDG_DATA_HOME") or (home / ".local" / "share"))

    app_dir = base_dir / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_config_path(app_name: str) -> Path:
    return get_app_data_dir(app_name) / "config.json"
