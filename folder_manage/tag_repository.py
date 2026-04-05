from __future__ import annotations

import csv
import json
from pathlib import Path

from app_paths import get_app_data_dir


class TagRepository:
    def __init__(self, app_name: str, file_name: str = "folder_tags.json"):
        self.base_dir = get_app_data_dir(app_name)
        self.file_path = self.base_dir / file_name
        self._tags_by_key: dict[str, list[str]] = {}
        self.load()

    def load(self) -> dict[str, list[str]]:
        if not self.file_path.exists():
            self._tags_by_key = {}
            return self._tags_by_key

        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        normalized: dict[str, list[str]] = {}
        for key, value in payload.items():
            tags = value if isinstance(value, list) else []
            normalized[str(key)] = self._normalize_tags(tags)
        self._tags_by_key = normalized
        return self._tags_by_key

    def save(self) -> None:
        self.file_path.write_text(
            json.dumps(self._tags_by_key, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_tags(self, key: str) -> list[str]:
        return list(self._tags_by_key.get(key, []))

    def get_effective_tags(self, relative_key: str) -> list[str]:
        """從根到葉累積：路徑上每一層若有自己的標籤則覆寫繼承結果，否則沿用上一層。"""
        key = (relative_key or "").strip().replace("\\", "/").strip("/")
        parts = [p for p in key.split("/") if p]
        if not parts:
            return []
        current: list[str] = []
        for i in range(len(parts)):
            prefix = "/".join(parts[: i + 1])
            own = self.get_tags(prefix)
            if own:
                current = list(own)
        return self._normalize_tags(current)

    def set_tags(self, key: str, tags: list[str]) -> None:
        clean = self._normalize_tags(tags)
        if clean:
            self._tags_by_key[key] = clean
        elif key in self._tags_by_key:
            del self._tags_by_key[key]
        self.save()

    def add_tags(self, key: str, tags: list[str]) -> list[str]:
        current = self.get_tags(key)
        merged = self._normalize_tags(current + tags)
        self._tags_by_key[key] = merged
        self.save()
        return merged

    def remove_key(self, key: str) -> None:
        if key in self._tags_by_key:
            del self._tags_by_key[key]
            self.save()

    def rename_relative_path_root(self, old_rel: str, new_rel: str) -> None:
        """當資料夾相對於主資料夾的路徑改變時，同步更新所有標籤鍵（含子路徑）。"""
        old_rel = (old_rel or "").strip().replace("\\", "/").strip("/")
        new_rel = (new_rel or "").strip().replace("\\", "/").strip("/")
        if not old_rel or not new_rel or old_rel == new_rel:
            return

        mapping: list[tuple[str, str]] = []
        for key in list(self._tags_by_key.keys()):
            if key == old_rel:
                mapping.append((key, new_rel))
            elif key.startswith(old_rel + "/"):
                mapping.append((key, new_rel + key[len(old_rel) :]))

        if not mapping:
            return

        new_key_tags: dict[str, list[str]] = {}
        for old_k, new_k in mapping:
            tags = self._tags_by_key.pop(old_k, [])
            new_key_tags[new_k] = self._normalize_tags(new_key_tags.get(new_k, []) + tags)

        for new_k, tags in new_key_tags.items():
            if new_k in self._tags_by_key:
                self._tags_by_key[new_k] = self._normalize_tags(self._tags_by_key[new_k] + tags)
            else:
                self._tags_by_key[new_k] = tags
        self.save()

    def remove_keys_by_prefix(self, prefix: str) -> int:
        clean_prefix = (prefix or "").strip().strip("/")
        if not clean_prefix:
            return 0
        keys_to_remove = [
            key for key in list(self._tags_by_key.keys()) if key == clean_prefix or key.startswith(clean_prefix + "/")
        ]
        if not keys_to_remove:
            return 0
        for key in keys_to_remove:
            del self._tags_by_key[key]
        self.save()
        return len(keys_to_remove)

    def get_all_tags(self) -> list[str]:
        merged: set[str] = set()
        for tags in self._tags_by_key.values():
            merged.update(tags)
        return sorted(merged, key=str.lower)

    def remove_tag_everywhere(self, tag: str) -> int:
        """Remove this tag from every subfolder entry. Returns number of keys updated."""
        clean = (tag or "").strip()
        if not clean:
            return 0
        token = clean.casefold()
        updated_keys = 0
        keys_to_delete: list[str] = []
        for key, tags in list(self._tags_by_key.items()):
            new_tags = [t for t in tags if t.casefold() != token]
            if len(new_tags) == len(tags):
                continue
            updated_keys += 1
            if new_tags:
                self._tags_by_key[key] = self._normalize_tags(new_tags)
            else:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del self._tags_by_key[key]
        if updated_keys:
            self.save()
        return updated_keys

    def export_json(self, output_path: Path) -> None:
        path = Path(output_path)
        path.write_text(json.dumps(self._tags_by_key, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_json(self, input_path: Path, merge: bool = True) -> None:
        path = Path(input_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON must be an object in format {path: [tags]}.")

        imported: dict[str, list[str]] = {}
        for key, value in payload.items():
            if not isinstance(value, list):
                continue
            imported[str(key)] = self._normalize_tags(value)

        if merge:
            for key, tags in imported.items():
                self._tags_by_key[key] = self._normalize_tags(self._tags_by_key.get(key, []) + tags)
        else:
            self._tags_by_key = imported
        self.save()

    def export_csv(self, output_path: Path) -> None:
        path = Path(output_path)
        with path.open("w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["subfolder_path", "tags"])
            for key in sorted(self._tags_by_key.keys(), key=str.lower):
                writer.writerow([key, ";".join(self._tags_by_key[key])])

    def import_csv(self, input_path: Path, merge: bool = True) -> None:
        path = Path(input_path)
        imported: dict[str, list[str]] = {}
        with path.open("r", newline="", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                key = (row.get("subfolder_path") or "").strip()
                tags_text = (row.get("tags") or "").strip()
                if not key:
                    continue
                tags = [x.strip() for x in tags_text.split(";") if x.strip()]
                imported[key] = self._normalize_tags(tags)

        if merge:
            for key, tags in imported.items():
                self._tags_by_key[key] = self._normalize_tags(self._tags_by_key.get(key, []) + tags)
        else:
            self._tags_by_key = imported
        self.save()

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            if not isinstance(tag, str):
                continue
            clean = tag.strip()
            if not clean:
                continue
            token = clean.casefold()
            if token in seen:
                continue
            seen.add(token)
            result.append(clean)
        result.sort(key=str.lower)
        return result
