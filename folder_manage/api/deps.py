from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from api.constants import APP_NAME
from api.services.file_operations import FileOperationsService
from api.services.preview_service import PreviewService
from api.services.scan_coordinator import ScanCoordinator
from api.services.thumbnail_service import ThumbnailService
from api.services.tree_service import TreeService
from app_paths import get_config_path
from folder_tags_migration import migrate_folder_tags_if_needed
from media_keyword_service import MediaKeywordService
from people_data_store import PeopleDataStore


class AppContext:
    def __init__(self):
        self.config_path = get_config_path(APP_NAME)
        self.config = self._load_config()
        self.store = PeopleDataStore()
        self.keyword_service = MediaKeywordService()
        self.thumbnail_service = ThumbnailService(APP_NAME)
        self.scan_coordinator = ScanCoordinator()
        self.preview_service = PreviewService(self.store, self.keyword_service, self.thumbnail_service)
        self.tree_service = TreeService(self.store, self.preview_service)
        self.file_ops = FileOperationsService(self.store)

        self.selected_filter_tags: set[str] = set()
        self.filter_media_video = False
        self.filter_media_image = False
        self.filter_duration_min: Optional[float] = None
        self.filter_duration_max: Optional[float] = None
        self.preview_sort_mode = "name"
        self.manual_entry_order: dict[str, list[str]] = {}
        self.manual_media_order: dict[str, list[str]] = {}
        self.migration_message: Optional[str] = None

        self._apply_saved_root()
        self._run_folder_tags_migration()

    def _load_config(self) -> dict:
        default = {"root_folder": "", "tree_child_order": {}}
        if self.config_path.exists():
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return {**default, **payload}
            except Exception:
                pass
        return default

    def save_config(self) -> None:
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _apply_saved_root(self) -> None:
        root_folder = (self.config.get("root_folder") or "").strip()
        if not root_folder:
            return
        root_path = Path(root_folder)
        if root_path.exists() and root_path.is_dir():
            self.store.set_root_folder(root_path)

    def _run_folder_tags_migration(self) -> None:
        try:
            self.migration_message = migrate_folder_tags_if_needed(self.store, self.keyword_service)
        except Exception:
            self.migration_message = None

    def shutdown(self) -> None:
        self.thumbnail_service.flush_disk_index()
        self.scan_coordinator.shutdown()


_ctx: Optional[AppContext] = None


def get_ctx() -> AppContext:
    global _ctx
    if _ctx is None:
        _ctx = AppContext()
    return _ctx
