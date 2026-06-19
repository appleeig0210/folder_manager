from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from api.services.thumbnail_service import ThumbnailService
from media_keyword_service import MediaKeywordService
from people_data_store import MediaItem, PeopleDataStore, SubfolderEntry


class PreviewService:
    def __init__(
        self,
        store: PeopleDataStore,
        keyword_service: MediaKeywordService,
        thumbnail_service: ThumbnailService,
    ):
        self.store = store
        self.keyword_service = keyword_service
        self.thumbnail_service = thumbnail_service
        self._folder_media_filter_cache: dict[tuple[str, str], bool] = {}
        self._folder_tag_filter_cache: dict[tuple[str, str], bool] = {}

    def clear_filter_cache(self) -> None:
        self._folder_media_filter_cache.clear()
        self._folder_tag_filter_cache.clear()

    @staticmethod
    def preview_name_sort_key(name: str) -> tuple[int, tuple[tuple[int, object], ...], str]:
        normalized = (name or "").strip()
        lower_name = normalized.casefold()
        starts_with_number = 0 if re.match(r"^\d+", normalized) else 1
        normalized_for_sort = re.sub(r"[_-]+", ".", lower_name)
        natural_tokens: list[tuple[int, object]] = []
        for token in re.findall(r"\d+|[^\d]+", normalized_for_sort):
            if token.isdigit():
                natural_tokens.append((0, int(token)))
            else:
                natural_tokens.append((1, token))
        return (starts_with_number, tuple(natural_tokens), lower_name)

    def sorted_entries(self, entries: list[SubfolderEntry], sort_mode: str) -> list[SubfolderEntry]:
        if sort_mode == "manual":
            return list(entries)
        if sort_mode == "time":
            def key(e: SubfolderEntry):
                try:
                    return (Path(e.subfolder_path).stat().st_mtime, self.preview_name_sort_key(e.subfolder_name))
                except Exception:
                    return (0.0, self.preview_name_sort_key(e.subfolder_name))
            return sorted(entries, key=key, reverse=True)
        if sort_mode == "type":
            def key(e: SubfolderEntry):
                t = (e.preview_type or "").lower()
                return (t, self.preview_name_sort_key(e.subfolder_name))
            return sorted(entries, key=key)
        return sorted(entries, key=lambda e: self.preview_name_sort_key(e.subfolder_name))

    def sorted_media(self, items: list[MediaItem], sort_mode: str) -> list[MediaItem]:
        if sort_mode == "manual":
            return list(items)
        if sort_mode == "time":
            def key(m: MediaItem):
                try:
                    return (Path(m.media_path).stat().st_mtime, self.preview_name_sort_key(m.media_path.name))
                except Exception:
                    return (0.0, self.preview_name_sort_key(m.media_path.name))
            return sorted(items, key=key, reverse=True)
        if sort_mode == "type":
            def key(m: MediaItem):
                ext = Path(m.media_path).suffix.lower()
                return (m.media_type, ext, self.preview_name_sort_key(m.media_path.name))
            return sorted(items, key=key)
        return sorted(items, key=lambda m: self.preview_name_sort_key(m.media_path.name))

    def media_matches_tag_filter(self, path: Path, selected_tags: set[str]) -> bool:
        if not selected_tags:
            return True
        file_tags = set(self.keyword_service.get_keywords(path))
        return bool(file_tags.intersection(selected_tags))

    def folder_contains_tagged_media(self, folder: Path, selected_tags: set[str]) -> bool:
        if not selected_tags:
            return True
        signature = "|".join(sorted(selected_tags, key=str.casefold))
        cache_key = (str(folder.resolve()), signature)
        cached = self._folder_tag_filter_cache.get(cache_key)
        if cached is not None:
            return cached

        items = self.store.list_media_items(folder)
        if not items:
            self._folder_tag_filter_cache[cache_key] = False
            return False

        keywords_map = self.keyword_service.read_keywords_batch([item.media_path for item in items])
        matched = False
        for item in items:
            tags = set(keywords_map.get(str(item.media_path.resolve()), []))
            if tags.intersection(selected_tags):
                matched = True
                break
        self._folder_tag_filter_cache[cache_key] = matched
        return matched

    def filter_media_by_tags(self, items: list[MediaItem], selected_tags: set[str]) -> list[MediaItem]:
        if not selected_tags:
            return list(items)
        keywords_map = self.keyword_service.read_keywords_batch([item.media_path for item in items])
        result: list[MediaItem] = []
        for item in items:
            tags = set(keywords_map.get(str(item.media_path.resolve()), []))
            if tags.intersection(selected_tags):
                result.append(item)
        return result

    @staticmethod
    def duration_filter_enabled(lo_min: Optional[float], hi_min: Optional[float]) -> bool:
        return lo_min is not None or hi_min is not None

    def media_item_matches_filter(
        self,
        item: MediaItem,
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> bool:
        if item.media_type == "image":
            if want_video and not want_image:
                return False
            return True
        if item.media_type != "video":
            return False
        if want_image and not want_video:
            return False
        if not self.duration_filter_enabled(lo_min, hi_min):
            return True
        sec = self.thumbnail_service.get_video_duration_seconds(item.media_path)
        if sec is None:
            return False
        lo_s = (lo_min * 60.0) if lo_min is not None else 0.0
        hi_s = (hi_min * 60.0) if hi_min is not None else float("inf")
        return lo_s <= sec <= hi_s

    def folder_matches_active_media_filter(
        self,
        folder: Path,
        lo_min: Optional[float],
        hi_min: Optional[float],
        want_video: bool,
        want_image: bool,
    ) -> bool:
        signature = f"v={int(want_video)}|i={int(want_image)}|lo={lo_min}|hi={hi_min}"
        cache_key = (str(folder.resolve()), signature)
        cached = self._folder_media_filter_cache.get(cache_key)
        if cached is not None:
            return cached
        items = self.store.list_media_items(folder)
        matched = any(
            self.media_item_matches_filter(item, want_video, want_image, lo_min, hi_min) for item in items
        )
        self._folder_media_filter_cache[cache_key] = matched
        return matched

    def filter_media_by_type(self, items: list[MediaItem], want_v: bool, want_i: bool) -> list[MediaItem]:
        if not want_v and not want_i:
            return list(items)
        if want_v and want_i:
            return list(items)
        if want_v:
            return [m for m in items if m.media_type == "video"]
        return [m for m in items if m.media_type == "image"]

    def filter_items_by_duration(
        self, items: list[MediaItem], lo_min: Optional[float], hi_min: Optional[float]
    ) -> list[MediaItem]:
        if not self.duration_filter_enabled(lo_min, hi_min):
            return list(items)
        return [
            m
            for m in items
            if self.media_item_matches_filter(m, True, True, lo_min, hi_min)
        ]

    def apply_media_filters(
        self,
        items: list[MediaItem],
        selected_tags: set[str],
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> list[MediaItem]:
        filtered = self.filter_media_by_tags(items, selected_tags)
        filtered = self.filter_media_by_type(filtered, want_video, want_image)
        return self.filter_items_by_duration(filtered, lo_min, hi_min)

    def scan_media_for_preview(
        self,
        folder: Path,
        selected_tags: set[str],
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> tuple[list[MediaItem], list[MediaItem]]:
        raw = self.store.list_media_items(folder)
        display = self.apply_media_filters(raw, selected_tags, want_video, want_image, lo_min, hi_min)
        return raw, display

    def scan_tagged_media_in_scope(
        self,
        scope_paths: list[Path],
        selected_tags: set[str],
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> list[MediaItem]:
        combined: list[MediaItem] = []
        seen: set[str] = set()
        for folder in scope_paths:
            folder = Path(folder).resolve()
            if not folder.is_dir():
                continue
            _, display = self.scan_media_for_preview(
                folder,
                selected_tags,
                want_video,
                want_image,
                lo_min,
                hi_min,
            )
            for item in display:
                key = str(item.media_path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                combined.append(item)
        return combined

    def apply_media_entry_filter(
        self,
        entries: list[SubfolderEntry],
        selected_tags: set[str],
        lo_min: Optional[float],
        hi_min: Optional[float],
        want_video: bool,
        want_image: bool,
    ) -> list[SubfolderEntry]:
        filtered = entries
        if selected_tags:
            filtered = [
                e for e in filtered if self.folder_contains_tagged_media(e.subfolder_path, selected_tags)
            ]
        if not want_video and not want_image and not self.duration_filter_enabled(lo_min, hi_min):
            return filtered
        return [
            e
            for e in filtered
            if self.folder_matches_active_media_filter(e.subfolder_path, lo_min, hi_min, want_video, want_image)
        ]

    def build_entry_for_folder(self, folder: Path, person_name: str) -> SubfolderEntry:
        preview_path, preview_type, media_count = self.store.get_folder_media_info(folder)
        return SubfolderEntry(
            person_name=person_name,
            subfolder_name=folder.name,
            subfolder_path=folder,
            relative_key=self.store.to_relative_key(folder),
            preview_path=preview_path,
            preview_type=preview_type,
            media_count=media_count,
        )

    def get_media_tags_map(self, items: list[MediaItem]) -> dict[str, list[str]]:
        return self.keyword_service.media_items_with_tags(self.store, items)
