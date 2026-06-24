from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from api.constants import APP_NAME
from app_paths import get_app_data_dir
from exiftool_session import ExifToolSession, exiftool_cli_path, run_exiftool_subprocess
from people_data_store import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaItem, PeopleDataStore
from tag_index_store import TagIndexStore


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
    META_ROOT_KEY = "root_folder"
    REBUILD_BATCH_SIZE = 400

    def __init__(self) -> None:
        self._cache_lock = threading.Lock()
        self._cache: dict[str, tuple[int, list[str]]] = {}
        self._exiftool_path: Path | None = None
        self._session: ExifToolSession | None = None
        self._index = TagIndexStore(get_app_data_dir(APP_NAME) / "tags_index.sqlite")
        self._scan_lock = threading.Lock()
        self._scanning = False
        self._scan_thread: threading.Thread | None = None
        self._exiftool_io_lock = threading.Lock()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        self._index.close()

    @property
    def index(self) -> TagIndexStore:
        return self._index

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    @property
    def index_ready(self) -> bool:
        return self._index.count() > 0

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
        exe_parent = Path(sys.executable).resolve().parent
        bundled_candidates = [
            exe_parent / "exiftool" / bundled_name,
            exe_parent.parent / "Resources" / "exiftool" / bundled_name,
        ]
        for bundled in bundled_candidates:
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

    def _get_session(self) -> ExifToolSession:
        exiftool = self.resolve_exiftool()
        if self._session is None:
            self._session = ExifToolSession(exiftool, self._exiftool_charset_args())
        return self._session

    def bind_root_folder(self, root: Path | None) -> None:
        if root is None:
            return
        root_key = str(root.resolve())
        stored = self._index.get_meta(self.META_ROOT_KEY)
        if stored != root_key:
            self._index.clear_all()
            self._index.set_meta(self.META_ROOT_KEY, root_key)
            with self._cache_lock:
                self._cache.clear()
        if self._index.count() == 0 and not self._scanning:
            self.schedule_background_rebuild(root, delay_seconds=4.0)

    def invalidate_all(self) -> None:
        with self._cache_lock:
            self._cache.clear()
        root_meta = self._index.get_meta(self.META_ROOT_KEY)
        if root_meta:
            self.schedule_background_resync(Path(root_meta))

    def invalidate_path(self, path: Path) -> None:
        key = str(Path(path).resolve())
        with self._cache_lock:
            self._cache.pop(key, None)
        self._index.delete_path(path)

    def rename_index_path(self, old_path: Path, new_path: Path) -> None:
        old_key = str(old_path.resolve())
        new_key = str(new_path.resolve())
        with self._cache_lock:
            cached = self._cache.pop(old_key, None)
            if cached is not None:
                self._cache[new_key] = cached
        self._index.rename_path(old_path, new_path)

    def rename_index_prefix(self, old_prefix: Path, new_prefix: Path) -> None:
        old_base = str(old_prefix.resolve())
        new_base = str(new_prefix.resolve())
        with self._cache_lock:
            rewritten: dict[str, tuple[int, list[str]]] = {}
            stale: list[str] = []
            for key, value in self._cache.items():
                norm = key.replace("\\", "/")
                old_norm = old_base.replace("\\", "/").rstrip("/")
                if norm == old_norm or norm.startswith(f"{old_norm}/"):
                    suffix = norm[len(old_norm) :].lstrip("/")
                    new_norm = new_base.replace("\\", "/").rstrip("/")
                    new_norm = new_norm if not suffix else f"{new_norm}/{suffix}"
                    new_key = new_norm.replace("/", "\\") if "\\" in key else new_norm
                    rewritten[new_key] = value
                    stale.append(key)
            for key in stale:
                self._cache.pop(key, None)
            self._cache.update(rewritten)
        self._index.rename_prefix(old_prefix, new_prefix)

    def delete_index_path(self, path: Path) -> None:
        key = str(path.resolve())
        with self._cache_lock:
            self._cache.pop(key, None)
        self._index.delete_path(path)

    def delete_index_under_prefix(self, prefix: Path) -> None:
        self._index.delete_under_prefix(prefix)
        prefix_norm = str(prefix.resolve()).replace("\\", "/").rstrip("/")
        with self._cache_lock:
            stale = [
                key
                for key in self._cache
                if key.replace("\\", "/") == prefix_norm or key.replace("\\", "/").startswith(f"{prefix_norm}/")
            ]
            for key in stale:
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

    @staticmethod
    def tag_key(tag: str) -> str:
        return (tag or "").strip().casefold()

    @classmethod
    def dedupe_tags_preserve_order(cls, tags: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            clean = (tag or "").strip()
            if not clean or cls._is_corrupted_tag(clean):
                continue
            token = clean.casefold()
            if token in seen:
                continue
            seen.add(token)
            result.append(clean)
        return result

    @classmethod
    def tags_match_any_selected(cls, file_tags: list[str], selected_tags: set[str]) -> bool:
        if not selected_tags:
            return True
        selected_keys = {cls.tag_key(tag) for tag in selected_tags}
        selected_keys.discard("")
        if not selected_keys:
            return True
        file_keys = {cls.tag_key(tag) for tag in file_tags}
        file_keys.discard("")
        return bool(file_keys.intersection(selected_keys))

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
        self._index.put_batch({key: (mtime_ns, normalized)})

    def _exiftool_charset_args(self) -> list[str]:
        args = ["-charset", "utf8"]
        if sys.platform.startswith("win"):
            args.extend(["-charset", "filename=utf8"])
        return args

    def _write_path_argfile(self, paths: list[Path]) -> Path:
        fd, name = tempfile.mkstemp(prefix="media_paths_", suffix=".txt")
        os.close(fd)
        argfile = Path(name)
        lines = "\n".join(exiftool_cli_path(path.resolve()) for path in paths)
        argfile.write_text(f"{lines}\n", encoding="utf-8")
        return argfile

    def _run_exiftool_for_paths(
        self,
        base_args: list[str],
        paths: list[Path],
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        if not paths:
            return subprocess.CompletedProcess(base_args, 1, "", "No paths")
        try:
            exiftool = self.resolve_exiftool()
            return run_exiftool_subprocess(
                exiftool,
                base_args,
                paths,
                charset_args=self._exiftool_charset_args(),
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(base_args, 1, "", str(exc))

    def _index_exiftool_items(self, payload: list, paths: list[Path]) -> dict[str, dict]:
        by_source: dict[str, dict] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            source = item.get("SourceFile")
            if not isinstance(source, str) or not source.strip():
                continue
            by_source[str(Path(source).resolve())] = item

        indexed: dict[str, dict] = {}
        for index, path in enumerate(paths):
            key = str(path.resolve())
            item = by_source.get(key)
            if item is None and index < len(payload) and isinstance(payload[index], dict):
                item = payload[index]
            indexed[key] = item or {}
        return indexed

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

    def _read_exiftool_batch(self, paths: list[Path]) -> dict[str, list[str]]:
        if not paths:
            return {}
        output: dict[str, list[str]] = {}
        try:
            exiftool = self.resolve_exiftool()
        except FileNotFoundError:
            return {str(path.resolve()): [] for path in paths}

        args = ["-json", "-s", "-s", "-s"]
        for field in self.READ_FIELDS:
            args.append(f"-{field}")
        with self._exiftool_io_lock:
            proc = self._run_exiftool_for_paths(args, paths, timeout=max(30, len(paths) * 2))
        if proc.returncode not in (0, 1):
            return {str(path.resolve()): [] for path in paths}
        try:
            payload = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            payload = []
        if not isinstance(payload, list):
            payload = []

        indexed = self._index_exiftool_items(payload, paths)
        for path in paths:
            key = str(path.resolve())
            item = indexed.get(key, {})
            tags = self._extract_tags_from_item(item)
            self._cache_set(path, tags)
            output[key] = tags
        return output

    def _build_write_payload(self, file_path: Path, tags: list[str]) -> dict[str, object]:
        payload: dict[str, object] = {
            "SourceFile": str(file_path.resolve()),
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

    def _write_keyword_args(self, file_path: Path, tags: list[str]) -> list[str]:
        clean = self._normalize_tags(tags)
        args = [
            "-overwrite_original",
            "-XMP-dc:Subject=",
            "-IPTC:Keywords=",
            "-Keywords=",
            "-XPKeywords=",
            "-IFD0:XPKeywords=",
            "-Keys:Keywords=",
            "-Quicktime:Keywords=",
            "-XMP-pdf:Keywords=",
        ]
        for tag in clean:
            args.append(f"-XMP-dc:Subject={tag}")
        if not clean:
            return args

        joined = "; ".join(clean)
        args.append(f"-IPTC:Keywords={joined}")
        args.append(f"-Keywords={joined}")
        suffix = file_path.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            args.append(f"-Keys:Keywords={joined}")
            args.append(f"-Quicktime:Keywords={joined}")
        if suffix in {".jpg", ".jpeg", ".tif", ".tiff"}:
            args.append(f"-IFD0:XPKeywords={joined}")
            args.append(f"-XPKeywords={joined}")
        return args

    def _write_keywords_with_exiftool(self, exiftool: Path, file_path: Path, tags: list[str]) -> subprocess.CompletedProcess[str]:
        resolved_path = Path(file_path).resolve()
        if not resolved_path.is_file():
            return subprocess.CompletedProcess([], 1, "", f"File not found: {exiftool_cli_path(resolved_path)}")
        args = self._write_keyword_args(resolved_path, tags)
        with self._exiftool_io_lock:
            return run_exiftool_subprocess(
                exiftool,
                args,
                [resolved_path],
                charset_args=self._exiftool_charset_args(),
                timeout=120,
            )

    def get_keywords(self, path: Path) -> list[str]:
        file_path = Path(path).resolve()
        if not file_path.is_file():
            return []
        cached = self._cache_get(file_path)
        if cached is not None:
            return cached
        result = self.read_keywords_batch([file_path])
        return list(result.get(str(file_path), []))

    def read_keywords_batch(self, paths: list[Path], *, fetch_misses: bool = True) -> dict[str, list[str]]:
        candidates: list[Path] = []
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
            candidates.append(path)

        if not candidates:
            return output

        index_hits, index_misses = self._index.get_batch(candidates)
        for key, tags in index_hits.items():
            normalized = self._normalize_tags(tags)
            path = Path(key)
            mtime_ns = self._file_mtime_ns(path)
            with self._cache_lock:
                self._cache[key] = (mtime_ns, normalized)
            output[key] = normalized

        if not index_misses:
            return output

        if not fetch_misses:
            for path in index_misses:
                output[str(path.resolve())] = []
            return output

        try:
            self.resolve_exiftool()
        except FileNotFoundError:
            for path in index_misses:
                output[str(path.resolve())] = []
            return output

        for offset in range(0, len(index_misses), self.REBUILD_BATCH_SIZE):
            chunk = index_misses[offset : offset + self.REBUILD_BATCH_SIZE]
            output.update(self._read_exiftool_batch(chunk))
        return output

    @staticmethod
    def _exiftool_write_succeeded(proc: subprocess.CompletedProcess[str]) -> bool:
        if proc.returncode == 0:
            return True
        combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".lower()
        return proc.returncode == 1 and "files updated" in combined

    def set_keywords(self, path: Path, tags: list[str]) -> list[str]:
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"找不到檔案：{file_path}")
        if file_path.suffix.lower() not in self.MEDIA_EXTENSIONS:
            raise ValueError(f"不支援的媒體格式：{file_path.suffix}")

        clean = self._normalize_tags(tags)
        exiftool = self.resolve_exiftool()
        proc = self._write_keywords_with_exiftool(exiftool, file_path, clean)

        if not self._exiftool_write_succeeded(proc):
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or "ExifTool 寫入失敗")

        self._cache_set(file_path, clean)
        return clean

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

    def list_media_files_in_scope(self, folders: list[Path]) -> list[Path]:
        files: list[Path] = []
        seen: set[str] = set()
        for folder in folders:
            folder = Path(folder).resolve()
            if not folder.is_dir():
                continue
            for path in self.iter_media_files(folder):
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
        return files

    def reconcile_scope(
        self,
        folders: list[Path],
        *,
        scan_new_files: bool = False,
        scan_limit: int = 80,
    ) -> None:
        if not folders:
            return
        if scan_new_files:
            disk_files = self.list_media_files_in_scope(folders)
            disk_set = {str(path.resolve()) for path in disk_files}
            self._index.prune_orphans_under_prefixes(folders, disk_set)
            _, misses = self._index.get_batch(disk_files)
            if misses:
                self.read_keywords_batch(misses[:scan_limit])
            return
        self._index.prune_stale_files_under_prefixes(folders)

    def schedule_background_rebuild(self, root: Path, *, delay_seconds: float = 0) -> None:
        root = Path(root).resolve()
        if not root.is_dir():
            return

        def worker() -> None:
            if delay_seconds > 0:
                import time
                time.sleep(delay_seconds)
            with self._scan_lock:
                if self._scanning:
                    return
                self._scanning = True
            try:
                media_paths = self.iter_media_files(root)
                for offset in range(0, len(media_paths), self.REBUILD_BATCH_SIZE):
                    chunk = media_paths[offset : offset + self.REBUILD_BATCH_SIZE]
                    _, misses = self._index.get_batch(chunk)
                    if misses:
                        self.read_keywords_batch(misses)
            finally:
                self._scanning = False

        if self._scan_thread and self._scan_thread.is_alive():
            return
        self._scan_thread = threading.Thread(target=worker, name="tag-index-rebuild", daemon=True)
        self._scan_thread.start()

    def schedule_background_resync(self, root: Path, *, delay_seconds: float = 0) -> None:
        root = Path(root).resolve()
        if not root.is_dir():
            return

        def worker() -> None:
            if delay_seconds > 0:
                import time
                time.sleep(delay_seconds)
            with self._scan_lock:
                if self._scanning:
                    return
                self._scanning = True
            try:
                media_paths = self.iter_media_files(root)
                for offset in range(0, len(media_paths), self.REBUILD_BATCH_SIZE):
                    chunk = media_paths[offset : offset + self.REBUILD_BATCH_SIZE]
                    self._read_exiftool_batch(chunk)
            finally:
                self._scanning = False

        if self._scan_thread and self._scan_thread.is_alive():
            return
        self._scan_thread = threading.Thread(target=worker, name="tag-index-resync", daemon=True)
        self._scan_thread.start()

    def collect_all_tags(self, store: PeopleDataStore) -> list[str]:
        if store.root_folder is None:
            return []
        root = store.ensure_root_folder()
        self.bind_root_folder(root)
        return self._index.get_all_unique_tags()

    def _paths_having_tags(self, tags: list[str]) -> list[Path]:
        return [
            Path(path)
            for path in self._index.paths_having_any_tag(tags)
            if Path(path).is_file() and Path(path).suffix.lower() in self.MEDIA_EXTENSIONS
        ]

    def _scan_disk_for_tags(self, root: Path, tags: list[str]) -> list[Path]:
        tokens = {(tag or "").strip().casefold() for tag in tags if (tag or "").strip()}
        if not tokens:
            return []
        paths: list[Path] = []
        seen: set[str] = set()
        for path in self.iter_media_files(root):
            key = str(path.resolve())
            if key in seen:
                continue
            current = self.get_keywords(path)
            if any(t.casefold() in tokens for t in current):
                seen.add(key)
                paths.append(path)
        return paths

    def _collect_paths_with_tags(self, store: PeopleDataStore, tags: list[str]) -> list[Path]:
        paths = self._paths_having_tags(tags)
        if paths or store.root_folder is None:
            return paths
        return self._scan_disk_for_tags(store.ensure_root_folder(), tags)

    def remove_tag_everywhere(self, store: PeopleDataStore, tag: str) -> tuple[int, list[str]]:
        return self.remove_tags_everywhere(store, [tag])

    def remove_tags_everywhere(self, store: PeopleDataStore, tags: list[str]) -> tuple[int, list[str]]:
        tokens = {(tag or "").strip().casefold() for tag in tags if (tag or "").strip()}
        if not tokens:
            return 0, []
        paths = self._collect_paths_with_tags(store, tags)
        updated = 0
        warnings: list[str] = []
        for path in paths:
            current = self.get_keywords(path)
            new_tags = [t for t in current if t.casefold() not in tokens]
            if len(new_tags) == len(current):
                continue
            try:
                self.set_keywords(path, new_tags)
                updated += 1
            except Exception as exc:
                warnings.append(f"{path.name}: {exc}")
        return updated, warnings

    def export_map(self, store: PeopleDataStore) -> dict[str, list[str]]:
        root = store.ensure_root_folder()
        self.reconcile_scope([root])
        exported: dict[str, list[str]] = {}
        for path_str in self._index.paths_under_prefix(root):
            path = Path(path_str)
            if not path.is_file():
                continue
            tags = self.get_keywords(path)
            if tags:
                exported[str(path.resolve())] = tags
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

    def paths_with_any_tag(
        self,
        selected_tags: set[str],
        *,
        under_prefix: Path | None = None,
    ) -> set[str]:
        return self._index.paths_with_any_tag(selected_tags, under_prefix=under_prefix)

    def folder_has_tagged_media_from_index(
        self,
        folder: Path,
        selected_tags: set[str],
        media_paths: list[Path],
    ) -> bool:
        if not selected_tags:
            return True
        hits, misses = self._index.get_batch(media_paths)
        for tags in hits.values():
            if self.tags_match_any_selected(tags, selected_tags):
                return True
        if misses:
            batch = self.read_keywords_batch(misses)
            for tags in batch.values():
                if self.tags_match_any_selected(tags, selected_tags):
                    return True
        return False
