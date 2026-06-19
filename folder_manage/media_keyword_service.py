from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from people_data_store import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaItem, PeopleDataStore


class MediaKeywordService:
    READ_FIELDS = (
        "XMP-dc:Subject",
        "Subject",
        "Keywords",
        "IPTC:Keywords",
        "XPKeywords",
        "Keys:Keywords",
        "Quicktime:Keywords",
        "XMP-pdf:Keywords",
    )
    MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

    def __init__(self) -> None:
        self._cache_lock = threading.Lock()
        self._cache: dict[str, tuple[int, list[str]]] = {}
        self._exiftool_path: Path | None = None

    def resolve_exiftool(self) -> Path:
        if self._exiftool_path is not None:
            return self._exiftool_path

        env_path = (os.environ.get("EXIFTOOL_PATH") or "").strip()
        if env_path:
            candidate = Path(env_path)
            if candidate.is_file():
                self._exiftool_path = candidate
                return candidate

        bundled_name = "exiftool.exe" if sys.platform.startswith("win") else "exiftool"
        bundled = Path(sys.executable).resolve().parent / "exiftool" / bundled_name
        if bundled.is_file():
            self._exiftool_path = bundled
            return bundled

        found = shutil.which("exiftool")
        if found:
            self._exiftool_path = Path(found)
            return self._exiftool_path

        raise FileNotFoundError(
            "找不到 ExifTool。請安裝並加入 PATH，或將 exiftool 放在 sidecar 同目錄的 exiftool/ 下。"
        )

    def invalidate_all(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def invalidate_path(self, path: Path) -> None:
        key = str(Path(path).resolve())
        with self._cache_lock:
            self._cache.pop(key, None)

    @staticmethod
    def _split_keyword_values(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                parts.extend(MediaKeywordService._split_keyword_values(item))
            return parts
        text = str(value).strip()
        if not text:
            return []
        if ";" in text:
            return [part.strip() for part in text.split(";") if part.strip()]
        return [text]

    @staticmethod
    def _is_corrupted_tag(tag: str) -> bool:
        stripped = (tag or "").strip()
        if not stripped:
            return True
        if "?" in stripped:
            return True
        if any(ord(ch) == 0xFFFD for ch in stripped):
            return True
        return False

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            if not isinstance(tag, str):
                continue
            clean = tag.strip()
            if not clean or self._is_corrupted_tag(clean):
                continue
            token = clean.casefold()
            if token in seen:
                continue
            seen.add(token)
            result.append(clean)
        result.sort(key=str.casefold)
        return result

    @staticmethod
    def _file_mtime_ns(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    def _cache_get(self, path: Path) -> list[str] | None:
        key = str(path.resolve())
        mtime_ns = self._file_mtime_ns(path)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            cached_mtime, tags = cached
            if cached_mtime != mtime_ns:
                self._cache.pop(key, None)
                return None
            return list(tags)

    def _cache_set(self, path: Path, tags: list[str]) -> None:
        key = str(path.resolve())
        mtime_ns = self._file_mtime_ns(path)
        normalized = self._normalize_tags(tags)
        with self._cache_lock:
            self._cache[key] = (mtime_ns, normalized)

    def _run_exiftool(self, args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def _get_field_value(self, item: dict, field: str) -> object | None:
        value = item.get(field)
        if value is not None:
            return value
        group_key = next(
            (
                k
                for k in item.keys()
                if k == field or k.endswith(f":{field}") or k.endswith(f"-{field}")
            ),
            None,
        )
        if group_key:
            return item.get(group_key)
        return None

    def _extract_tags_from_item(self, item: dict) -> list[str]:
        field_groups = (
            ("XMP-dc:Subject", "Subject"),
            ("Keys:Keywords", "Quicktime:Keywords"),
            ("IFD0:XPKeywords", "XPKeywords"),
            ("Keywords", "IPTC:Keywords", "XMP-pdf:Keywords"),
        )
        for group in field_groups:
            merged: list[str] = []
            for field in group:
                value = self._get_field_value(item, field)
                if value is None:
                    continue
                merged.extend(self._split_keyword_values(value))
            normalized = self._normalize_tags(merged)
            if normalized:
                return normalized
        return []

    def _build_write_payload(self, file_path: Path, tags: list[str]) -> dict[str, object]:
        payload: dict[str, object] = {
            "XMP-dc:Subject": list(tags) if tags else [],
            "IPTC:Keywords": "",
            "Keys:Keywords": "",
            "Quicktime:Keywords": "",
            "IFD0:XPKeywords": "",
            "XPKeywords": "",
            "XMP-pdf:Keywords": "",
        }
        if not tags:
            return payload

        joined = "; ".join(tags)
        suffix = file_path.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            payload["Keys:Keywords"] = joined
            payload["Quicktime:Keywords"] = joined
        if suffix in {".jpg", ".jpeg", ".tif", ".tiff"}:
            payload["IFD0:XPKeywords"] = joined
            payload["XPKeywords"] = joined
        return payload

    def _write_keywords_with_exiftool(self, exiftool: Path, file_path: Path, tags: list[str]) -> subprocess.CompletedProcess[str]:
        payload = self._build_write_payload(file_path, tags)
        tmp_json = Path(tempfile.gettempdir()) / f"media_tags_{os.getpid()}_{file_path.stem}.json"
        try:
            tmp_json.write_text(json.dumps([payload], ensure_ascii=False), encoding="utf-8")
            args = [
                str(exiftool),
                "-overwrite_original",
                "-charset",
                "utf8",
                f"-j={tmp_json}",
                str(file_path),
            ]
            return self._run_exiftool(args, timeout=120)
        finally:
            tmp_json.unlink(missing_ok=True)

    def get_keywords(self, path: Path) -> list[str]:
        file_path = Path(path).resolve()
        if not file_path.is_file():
            return []
        cached = self._cache_get(file_path)
        if cached is not None:
            return cached
        result = self.read_keywords_batch([file_path])
        return list(result.get(str(file_path), []))

    def read_keywords_batch(self, paths: list[Path]) -> dict[str, list[str]]:
        existing: list[Path] = []
        output: dict[str, list[str]] = {}
        for raw in paths:
            path = Path(raw).resolve()
            key = str(path)
            if not path.is_file():
                output[key] = []
                continue
            if path.suffix.lower() not in self.MEDIA_EXTENSIONS:
                output[key] = []
                continue
            cached = self._cache_get(path)
            if cached is not None:
                output[key] = cached
                continue
            existing.append(path)

        if not existing:
            return output

        exiftool = self.resolve_exiftool()
        args = [
            str(exiftool),
            "-json",
            "-charset",
            "utf8",
            "-s",
            "-s",
            "-s",
        ]
        for field in self.READ_FIELDS:
            args.append(f"-{field}")
        args.extend(str(p) for p in existing)

        try:
            proc = self._run_exiftool(args, timeout=max(30, len(existing) * 2))
        except (OSError, subprocess.TimeoutExpired):
            for path in existing:
                output[str(path.resolve())] = []
            return output

        if proc.returncode not in (0, 1):
            for path in existing:
                output[str(path.resolve())] = []
            return output

        try:
            payload = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            payload = []

        if not isinstance(payload, list):
            payload = []

        for index, path in enumerate(existing):
            key = str(path.resolve())
            item: dict = {}
            if index < len(payload) and isinstance(payload[index], dict):
                item = payload[index]
            tags = self._extract_tags_from_item(item)
            self._cache_set(path, tags)
            output[key] = tags

        return output

    def set_keywords(self, path: Path, tags: list[str]) -> list[str]:
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"找不到檔案：{file_path}")
        if file_path.suffix.lower() not in self.MEDIA_EXTENSIONS:
            raise ValueError(f"不支援的媒體格式：{file_path.suffix}")

        clean = self._normalize_tags(tags)
        exiftool = self.resolve_exiftool()
        proc = self._write_keywords_with_exiftool(exiftool, file_path, clean)

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or "ExifTool 寫入失敗")

        self.invalidate_path(file_path)
        persisted = self._normalize_tags(list(self.read_keywords_batch([file_path]).get(str(file_path), [])))
        if clean and not persisted:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or "標籤寫入後無法從檔案讀回，可能是格式不支援或編碼失敗")

        self._cache_set(file_path, persisted if clean else [])
        return persisted if clean else []

    def add_keywords(self, path: Path, tags: list[str]) -> list[str]:
        current = self.get_keywords(path)
        merged = self._normalize_tags(current + tags)
        return self.set_keywords(path, merged)

    def add_keywords_batch(self, paths: list[Path], tags: list[str]) -> tuple[int, list[str]]:
        warnings: list[str] = []
        updated = 0
        for raw in paths:
            path = Path(raw).resolve()
            try:
                self.add_keywords(path, tags)
                updated += 1
            except Exception as exc:
                warnings.append(f"{path.name}: {exc}")
        return updated, warnings

    def set_keywords_batch(self, paths: list[Path], tags: list[str]) -> tuple[int, list[str]]:
        warnings: list[str] = []
        updated = 0
        for raw in paths:
            path = Path(raw).resolve()
            try:
                self.set_keywords(path, tags)
                updated += 1
            except Exception as exc:
                warnings.append(f"{path.name}: {exc}")
        return updated, warnings

    def iter_media_files(self, root: Path) -> list[Path]:
        root = Path(root).resolve()
        if not root.is_dir():
            return []
        files: list[Path] = []
        for dirpath, _, filenames in os.walk(root):
            dir_path = Path(dirpath)
            for name in filenames:
                path = dir_path / name
                if path.suffix.lower() in self.MEDIA_EXTENSIONS:
                    files.append(path)
        return files

    def collect_all_tags(self, store: PeopleDataStore) -> list[str]:
        root = store.ensure_root_folder()
        media_paths = self.iter_media_files(root)
        if not media_paths:
            return []
        keywords_map = self.read_keywords_batch(media_paths)
        merged: set[str] = set()
        for tags in keywords_map.values():
            merged.update(tags)
        return sorted(merged, key=str.casefold)

    def remove_tag_everywhere(self, store: PeopleDataStore, tag: str) -> int:
        token = (tag or "").strip().casefold()
        if not token:
            return 0
        root = store.ensure_root_folder()
        updated = 0
        for path in self.iter_media_files(root):
            current = self.get_keywords(path)
            new_tags = [t for t in current if t.casefold() != token]
            if len(new_tags) == len(current):
                continue
            self.set_keywords(path, new_tags)
            updated += 1
        return updated

    def remove_tags_everywhere(self, store: PeopleDataStore, tags: list[str]) -> int:
        tokens = {(tag or "").strip().casefold() for tag in tags if (tag or "").strip()}
        if not tokens:
            return 0
        root = store.ensure_root_folder()
        updated = 0
        for path in self.iter_media_files(root):
            current = self.get_keywords(path)
            new_tags = [t for t in current if t.casefold() not in tokens]
            if len(new_tags) == len(current):
                continue
            self.set_keywords(path, new_tags)
            updated += 1
        return updated

    def export_map(self, store: PeopleDataStore) -> dict[str, list[str]]:
        root = store.ensure_root_folder()
        media_paths = self.iter_media_files(root)
        keywords_map = self.read_keywords_batch(media_paths)
        exported: dict[str, list[str]] = {}
        for path in media_paths:
            key = str(path.resolve())
            tags = keywords_map.get(key, [])
            if tags:
                exported[key] = tags
        return exported

    def import_map(self, store: PeopleDataStore, payload: dict[str, list[str]], merge: bool = True) -> int:
        updated = 0
        for raw_path, tags in payload.items():
            path = Path(raw_path)
            if not path.is_file():
                continue
            if not isinstance(tags, list):
                continue
            clean = self._normalize_tags([str(t) for t in tags])
            if merge:
                self.add_keywords(path, clean)
            else:
                self.set_keywords(path, clean)
            updated += 1
        return updated

    def media_items_with_tags(
        self,
        store: PeopleDataStore,
        items: list[MediaItem],
    ) -> dict[str, list[str]]:
        paths = [item.media_path for item in items]
        return self.read_keywords_batch(paths)
