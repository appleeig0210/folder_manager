from __future__ import annotations

import json
import os
from pathlib import Path

from api.constants import APP_NAME
from app_paths import get_app_data_dir
from media_keyword_service import MediaKeywordService
from people_data_store import PeopleDataStore


def migrate_folder_tags_if_needed(store: PeopleDataStore, keyword_service: MediaKeywordService) -> str | None:
    app_dir = get_app_data_dir(APP_NAME)
    legacy_path = app_dir / "folder_tags.json"
    backup_path = app_dir / "folder_tags.json.bak"

    if not legacy_path.exists() or backup_path.exists():
        return None
    if store.root_folder is None:
        return None

    try:
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    except Exception:
        legacy_path.rename(backup_path)
        return "舊版 folder_tags.json 無法解析，已備份為 .bak"

    if not isinstance(payload, dict) or not payload:
        legacy_path.rename(backup_path)
        return None

    root = store.ensure_root_folder()
    migrated_files = 0
    for relative_key, tags in payload.items():
        if not isinstance(tags, list):
            continue
        clean_tags = [str(t).strip() for t in tags if str(t).strip()]
        if not clean_tags:
            continue
        folder = (root / str(relative_key).replace("/", os.sep)).resolve()
        if not folder.is_dir():
            continue
        for media_path in keyword_service.iter_media_files(folder):
            try:
                keyword_service.add_keywords(media_path, clean_tags)
                migrated_files += 1
            except Exception:
                continue

    legacy_path.rename(backup_path)
    return f"已將舊版資料夾標籤遷移至 {migrated_files} 個媒體檔，folder_tags.json 已備份"
