from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from media_path_filters import is_junk_filename, is_junk_path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


@dataclass
class SubfolderEntry:
    person_name: str
    subfolder_name: str
    subfolder_path: Path
    relative_key: str
    preview_path: Optional[Path]
    preview_type: Optional[str]
    media_count: int


@dataclass
class MediaItem:
    media_path: Path
    media_type: str


@dataclass
class FolderIndexCacheEntry:
    signature: tuple[int, int]
    media_items: list[MediaItem]
    preview_path: Optional[Path]
    preview_type: Optional[str]
    media_count: int
    scanned_at: float


class PeopleDataStore:
    def __init__(self, root_folder: Optional[Path] = None):
        self.root_folder: Optional[Path] = None
        self._cache_lock = threading.Lock()
        self._folder_index_cache: dict[str, FolderIndexCacheEntry] = {}
        if root_folder:
            self.set_root_folder(root_folder)

    def set_root_folder(self, root_folder: Path) -> None:
        root = Path(root_folder).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Root folder does not exist: {root}")
        self.root_folder = root
        self.clear_cache()

    def ensure_root_folder(self) -> Path:
        if self.root_folder is None:
            raise ValueError("Root folder is not configured.")
        return self.root_folder

    def get_people_folders(self) -> list[Path]:
        root = self.ensure_root_folder()
        people = [p for p in root.iterdir() if p.is_dir()]
        return sorted(people, key=lambda p: p.name.lower())

    def get_subfolders(self, person_folder: Path) -> list[Path]:
        folder = Path(person_folder)
        subfolders = [p for p in folder.iterdir() if p.is_dir()]
        return sorted(subfolders, key=lambda p: p.name.lower())

    def to_relative_key(self, folder: Path) -> str:
        root = self.ensure_root_folder()
        rel = Path(folder).resolve().relative_to(root)
        return rel.as_posix()

    def scan_person_subfolders(self, person_folder: Path) -> list[SubfolderEntry]:
        person = Path(person_folder)
        entries: list[SubfolderEntry] = []
        for subfolder in self.get_subfolders(person):
            preview_path, preview_type, media_count = self.get_folder_media_info(subfolder)
            entries.append(
                SubfolderEntry(
                    person_name=person.name,
                    subfolder_name=subfolder.name,
                    subfolder_path=subfolder,
                    relative_key=self.to_relative_key(subfolder),
                    preview_path=preview_path,
                    preview_type=preview_type,
                    media_count=media_count,
                )
            )
        return entries

    def scan_all(self) -> dict[str, list[SubfolderEntry]]:
        all_data: dict[str, list[SubfolderEntry]] = {}
        for person_folder in self.get_people_folders():
            all_data[person_folder.name] = self.scan_person_subfolders(person_folder)
        return all_data

    def get_folder_media_info(self, folder: Path) -> tuple[Optional[Path], Optional[str], int]:
        cache = self._get_or_scan_folder(Path(folder))
        return cache.preview_path, cache.preview_type, cache.media_count

    def get_folder_preview_samples(self, folder: Path, limit: int = 3) -> list[tuple[Path, str]]:
        cache = self._get_or_scan_folder(Path(folder))
        samples: list[tuple[Path, str]] = []
        for item in cache.media_items:
            if len(samples) >= limit:
                break
            samples.append((item.media_path, item.media_type))
        return samples

    def get_subfolder_entries_shallow(self, person_folder: Path) -> list[SubfolderEntry]:
        """Only list direct child folders and preview metadata."""
        person = Path(person_folder)
        entries: list[SubfolderEntry] = []
        for subfolder in self.get_subfolders(person):
            preview_path, preview_type, media_count = self.get_folder_media_info(subfolder)
            entries.append(
                SubfolderEntry(
                    person_name=person.name,
                    subfolder_name=subfolder.name,
                    subfolder_path=subfolder,
                    relative_key=self.to_relative_key(subfolder),
                    preview_path=preview_path,
                    preview_type=preview_type,
                    media_count=media_count,
                )
            )
        return entries

    def list_media_items(self, folder: Path) -> list[MediaItem]:
        target = Path(folder)
        if not target.exists() or not target.is_dir():
            return []
        cache = self._get_or_scan_folder(target)
        return list(cache.media_items)

    def list_direct_media_items(self, folder: Path) -> list[MediaItem]:
        target = Path(folder).resolve()
        if not target.exists() or not target.is_dir():
            return []
        items: list[MediaItem] = []
        try:
            children = sorted(target.iterdir(), key=lambda p: p.name.lower())
        except Exception:
            return []
        for path in children:
            if not path.is_file() or is_junk_path(path):
                continue
            suffix = path.suffix.lower()
            if suffix in IMAGE_EXTENSIONS:
                items.append(MediaItem(media_path=path, media_type="image"))
            elif suffix in VIDEO_EXTENSIONS:
                items.append(MediaItem(media_path=path, media_type="video"))
        return items

    def get_folder_media_type_flags(self, folder: Path) -> tuple[bool, bool]:
        """遞迴掃描資料夾底下是否含圖片／影片（使用快取）。"""
        cache = self._get_or_scan_folder(Path(folder))
        has_image = any(m.media_type == "image" for m in cache.media_items)
        has_video = any(m.media_type == "video" for m in cache.media_items)
        return has_image, has_video

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._folder_index_cache.clear()

    def invalidate_folder_cache(self, folder: Path) -> None:
        key = str(Path(folder).resolve())
        with self._cache_lock:
            self._folder_index_cache.pop(key, None)

    def _scan_folder_media_items(self, folder: Path) -> list[MediaItem]:
        items: list[MediaItem] = []
        for root, _, files in os.walk(folder):
            root_path = Path(root)
            dir_items: list[MediaItem] = []
            for file_name in files:
                if is_junk_filename(file_name):
                    continue
                suffix = Path(file_name).suffix.lower()
                path = root_path / file_name
                if suffix in IMAGE_EXTENSIONS:
                    dir_items.append(MediaItem(media_path=path, media_type="image"))
                elif suffix in VIDEO_EXTENSIONS:
                    dir_items.append(MediaItem(media_path=path, media_type="video"))
            if dir_items:
                dir_items.sort(key=lambda m: m.media_path.name.lower())
                items.extend(dir_items)
        return items

    def _scan_media_info_from_items(self, items: list[MediaItem]) -> tuple[Optional[Path], Optional[str], int]:
        first_image: Optional[Path] = None
        first_video: Optional[Path] = None
        for item in items:
            if item.media_type == "image" and first_image is None:
                first_image = item.media_path
            elif item.media_type == "video" and first_video is None:
                first_video = item.media_path

        if first_image:
            return first_image, "image", len(items)
        if first_video:
            return first_video, "video", len(items)
        return None, None, len(items)

    def _folder_signature(self, folder: Path) -> tuple[int, int]:
        """
        Signature for cache invalidation.
        - folder mtime
        - direct children count
        """
        try:
            folder_mtime = folder.stat().st_mtime_ns
        except Exception:
            folder_mtime = 0
        try:
            child_count = sum(1 for child in folder.iterdir() if not is_junk_path(child))
        except Exception:
            child_count = 0
        return folder_mtime, child_count

    def _get_or_scan_folder(self, folder: Path) -> FolderIndexCacheEntry:
        target = Path(folder).resolve()
        signature = self._folder_signature(target)
        key = str(target)

        with self._cache_lock:
            cached = self._folder_index_cache.get(key)
            if cached and cached.signature == signature:
                return cached

        media_items = self._scan_folder_media_items(target)
        preview_path, preview_type, media_count = self._scan_media_info_from_items(media_items)
        entry = FolderIndexCacheEntry(
            signature=signature,
            media_items=media_items,
            preview_path=preview_path,
            preview_type=preview_type,
            media_count=media_count,
            scanned_at=time.time(),
        )
        with self._cache_lock:
            self._folder_index_cache[key] = entry
        return entry

    def open_folder(self, folder: Path) -> None:
        path = Path(folder).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Folder does not exist: {path}")

        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def move_folder_content_and_remove_source(self, source_folder: Path, target_folder: Path) -> tuple[int, int, bool]:
        src = Path(source_folder).resolve()
        dst = Path(target_folder).resolve()
        self._validate_archive_paths(src, dst)

        moved_count = 0
        renamed_count = 0
        children = sorted(src.iterdir(), key=lambda p: p.name.lower())
        has_direct_child_dirs = any(item.is_dir() for item in children)

        # Move only non-folder files from current level.
        # Keep all child folders in source as-is.
        for item in children:
            if item.is_dir():
                continue
            target_path = dst / item.name
            if target_path.exists():
                target_path = self._build_non_conflict_path(dst, item.name)
                renamed_count += 1
            shutil.move(str(item), str(target_path))
            moved_count += 1

        source_deleted = False
        if src.exists() and not has_direct_child_dirs:
            shutil.rmtree(src)
            source_deleted = True

        self.clear_cache()

        return moved_count, renamed_count, source_deleted

    def delete_folder(self, folder: Path) -> int:
        target = Path(folder).resolve()
        if not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"Folder does not exist: {target}")

        file_count = 0
        for root, _, files in os.walk(target):
            file_count += len(files)

        shutil.rmtree(target)
        self.invalidate_folder_cache(target)
        return file_count

    def _validate_archive_paths(self, src: Path, dst: Path) -> None:
        if not src.exists() or not src.is_dir():
            raise FileNotFoundError(f"Source folder does not exist: {src}")
        if not dst.exists() or not dst.is_dir():
            raise FileNotFoundError(f"Target folder does not exist: {dst}")
        if src == dst:
            raise ValueError("Source and target cannot be the same folder.")
        if dst.is_relative_to(src):
            raise ValueError("Target folder cannot be inside source folder.")
        if src.is_relative_to(dst):
            raise ValueError("Source folder cannot be inside target folder.")

    def _build_non_conflict_path(self, folder: Path, base_name: str) -> Path:
        candidate = folder / base_name
        if not candidate.exists():
            return candidate

        stem = Path(base_name).stem
        suffix = Path(base_name).suffix
        index = 1
        while True:
            next_name = f"{stem}_moved_{index}{suffix}"
            candidate = folder / next_name
            if not candidate.exists():
                return candidate
            index += 1
