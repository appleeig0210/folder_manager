from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from api.services.preview_service import PreviewService
from media_path_filters import is_junk_path
from people_data_store import PeopleDataStore, SubfolderEntry


class TreeService:
    def __init__(
        self,
        store: PeopleDataStore,
        preview_service: PreviewService,
    ):
        self.store = store
        self.preview = preview_service

    def get_ordered_people_folders(self, child_order: dict[str, list[str]]) -> list[Path]:
        people = self.store.get_people_folders()
        order_map = child_order.get("__root__", [])
        if not order_map:
            return people
        order_index = {name: i for i, name in enumerate(order_map)}
        return sorted(people, key=lambda p: (order_index.get(p.name, 10_000), p.name.casefold()))

    def get_ordered_subfolders(self, parent: Path, child_order: dict[str, list[str]]) -> list[Path]:
        subs = self.store.get_subfolders(parent)
        key = str(parent.resolve())
        order_map = child_order.get(key, [])
        if not order_map:
            return subs
        order_index = {name: i for i, name in enumerate(order_map)}
        return sorted(subs, key=lambda p: (order_index.get(p.name, 10_000), p.name.casefold()))

    def folder_has_subdirs(self, folder_path: Path) -> bool:
        try:
            for child in folder_path.iterdir():
                if child.is_dir():
                    return True
        except Exception:
            return False
        return False

    def build_tree_nodes(
        self,
        *,
        selected_filter_tags: set[str],
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
        child_order: dict[str, list[str]],
    ) -> list[dict]:
        if self.store.root_folder is None:
            return []

        root = self.store.root_folder
        nodes: list[dict] = [
            {
                "id": str(root.resolve()),
                "name": root.name,
                "path": str(root.resolve()),
                "type": "root",
                "children": [],
            }
        ]
        root_node = nodes[0]

        if selected_filter_tags:
            self._build_tag_filtered_children(
                root_node,
                root,
                selected_filter_tags,
                want_video,
                want_image,
                lo_min,
                hi_min,
                child_order,
            )
        else:
            for person_folder in self.get_ordered_people_folders(child_order):
                if not self._tree_folder_visible(person_folder, want_video, want_image, lo_min, hi_min):
                    continue
                person_node = {
                    "id": str(person_folder.resolve()),
                    "name": person_folder.name,
                    "path": str(person_folder.resolve()),
                    "type": "person",
                    "children": [],
                }
                self._populate_person_shallow(
                    person_node,
                    person_folder,
                    want_video,
                    want_image,
                    lo_min,
                    hi_min,
                    child_order,
                )
                root_node["children"].append(person_node)
        return nodes

    def _populate_person_shallow(
        self,
        person_node: dict,
        person_folder: Path,
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
        child_order: dict[str, list[str]],
    ) -> None:
        for subfolder in self.get_ordered_subfolders(person_folder, child_order):
            if not self._tree_folder_visible(subfolder, want_video, want_image, lo_min, hi_min):
                continue
            child = {
                "id": str(subfolder.resolve()),
                "name": subfolder.name,
                "path": str(subfolder.resolve()),
                "type": "subfolder",
                "children": self._stub_children_if_has_subdirs(
                    subfolder, want_video, want_image, lo_min, hi_min
                ),
            }
            person_node["children"].append(child)

    def _stub_children_if_has_subdirs(
        self,
        folder_path: Path,
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> list[dict]:
        if not self._folder_has_visible_subdirs(folder_path, want_video, want_image, lo_min, hi_min):
            return []
        return [{"id": f"{folder_path.resolve()}::__stub__", "name": "…", "path": "", "type": "stub", "children": []}]

    def _folder_has_visible_subdirs(
        self,
        folder_path: Path,
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> bool:
        if not want_video and not want_image and not PreviewService.duration_filter_enabled(lo_min, hi_min):
            return self.folder_has_subdirs(folder_path)
        try:
            for sub in self.store.get_subfolders(folder_path):
                if self.preview.folder_matches_active_media_filter(sub, lo_min, hi_min, want_video, want_image):
                    return True
        except Exception:
            return False
        return False

    def _tree_folder_visible(
        self,
        folder: Path,
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> bool:
        if not want_video and not want_image and not PreviewService.duration_filter_enabled(lo_min, hi_min):
            return True
        return self.preview.folder_matches_active_media_filter(folder, lo_min, hi_min, want_video, want_image)

    def _build_tag_filtered_children(
        self,
        parent_node: dict,
        parent_folder: Path,
        selected_filter_tags: set[str],
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
        child_order: dict[str, list[str]],
    ) -> None:
        root = self.store.ensure_root_folder()
        for person_folder in self.get_ordered_people_folders(child_order):
            matching_keys, entries = self._collect_tag_filter_for_person(
                person_folder,
                person_folder.name,
                selected_filter_tags,
                lo_min,
                hi_min,
                want_video,
                want_image,
            )
            if not matching_keys and not entries:
                continue
            person_node = {
                "id": str(person_folder.resolve()),
                "name": person_folder.name,
                "path": str(person_folder.resolve()),
                "type": "person",
                "children": [],
            }
            visible_paths = {e.subfolder_path.resolve() for e in entries}
            for subfolder in self.get_ordered_subfolders(person_folder, child_order):
                if subfolder.resolve() not in visible_paths:
                    continue
                child = {
                    "id": str(subfolder.resolve()),
                    "name": subfolder.name,
                    "path": str(subfolder.resolve()),
                    "type": "subfolder",
                    "children": [],
                }
                person_node["children"].append(child)
            if person_node["children"] or person_folder.resolve() == root.resolve():
                parent_node["children"].append(person_node)

    def _collect_tag_filter_for_person(
        self,
        person_folder: Path,
        person_name: str,
        selected_filter_tags: set[str],
        lo_min: Optional[float],
        hi_min: Optional[float],
        want_video: bool,
        want_image: bool,
    ) -> tuple[set[str], list[SubfolderEntry]]:
        matching_keys: set[str] = set()
        if self.preview.keyword_service.index_ready:
            matching_paths = self.preview.keyword_service.paths_with_any_tag(
                selected_filter_tags,
                under_prefix=person_folder,
            )
            for path_str in matching_paths:
                path = Path(path_str)
                if not path.is_file() or is_junk_path(path):
                    continue
                try:
                    folder = path.parent
                    rk = self.store.to_relative_key(folder)
                except Exception:
                    continue
                if not self.preview.folder_matches_active_media_filter(
                    folder, lo_min, hi_min, want_video, want_image
                ):
                    continue
                matching_keys.add(rk)
        else:
            try:
                for dirpath, dirnames, _ in os.walk(person_folder):
                    for d in dirnames:
                        path = Path(dirpath) / d
                        try:
                            rk = self.store.to_relative_key(path)
                        except Exception:
                            continue
                        if self.preview.folder_contains_tagged_media(path, selected_filter_tags):
                            if not self.preview.folder_matches_active_media_filter(
                                path, lo_min, hi_min, want_video, want_image
                            ):
                                continue
                            matching_keys.add(rk)
            except Exception:
                return set(), []

        entries: list[SubfolderEntry] = []
        for rk in sorted(matching_keys):
            try:
                folder = (self.store.ensure_root_folder() / rk.replace("/", os.sep)).resolve()
            except Exception:
                continue
            if folder.is_dir():
                entries.append(self.preview.build_entry_for_folder(folder, person_name))
        return matching_keys, entries

    def expand_node(self, path: str) -> list[dict]:
        folder = Path(path).resolve()
        if not folder.is_dir():
            return []
        children: list[dict] = []
        for sub in self.store.get_subfolders(folder):
            children.append({
                "id": str(sub.resolve()),
                "name": sub.name,
                "path": str(sub.resolve()),
                "type": "subfolder",
                "children": self._stub_children_if_has_subdirs(sub, False, False, None, None),
            })
        return children

    def get_breadcrumb(self, path: str) -> list[dict]:
        if self.store.root_folder is None:
            return []
        root = self.store.root_folder.resolve()
        target = Path(path).resolve()
        try:
            rel = target.relative_to(root)
        except ValueError:
            return [{"name": root.name, "path": str(root)}]
        crumbs = [{"name": root.name, "path": str(root)}]
        current = root
        for part in rel.parts:
            current = current / part
            crumbs.append({"name": part, "path": str(current.resolve())})
        return crumbs
