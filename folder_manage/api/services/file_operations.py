from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional
import re

from people_data_store import PeopleDataStore
from tag_repository import TagRepository


class FileOperationsService:
    INVALID_CHARS = {'\\', '/', ':', '*', '?', '"', '<', '>', '|'}

    def __init__(self, store: PeopleDataStore, tag_repo: TagRepository):
        self.store = store
        self.tag_repo = tag_repo

    @classmethod
    def is_valid_folder_basename(cls, name: str) -> bool:
        s = (name or "").strip()
        if not s or s in (".", ".."):
            return False
        return not any(c in s for c in cls.INVALID_CHARS)

    @classmethod
    def is_valid_file_stem(cls, stem: str) -> bool:
        s = (stem or "").strip()
        if not s:
            return False
        return not any(c in s for c in cls.INVALID_CHARS)

    @staticmethod
    def _unique_temp_path(original: Path) -> Path:
        token = uuid.uuid4().hex[:8]
        return original.with_name(f"{original.name}.tmp_batch_{token}")

    @staticmethod
    def build_non_conflict_file_path(folder: Path, base_name: str) -> Path:
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

    @staticmethod
    def build_parenthesized_non_conflict_path(folder: Path, base_name: str) -> Path:
        candidate = folder / base_name
        if not candidate.exists():
            return candidate
        stem = Path(base_name).stem
        suffix = Path(base_name).suffix
        index = 1
        while True:
            candidate = folder / f"{stem}({index}){suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    @staticmethod
    def _count_files(folder: Path) -> int:
        return sum(1 for item in Path(folder).rglob("*") if item.is_file())

    @staticmethod
    def _numbered_screenshot_base(stem: str) -> str:
        match = re.match(r"^(?P<base>.+)-(?P<number>\d+)$", stem)
        return match.group("base") if match else stem

    @classmethod
    def build_next_video_frame_path(cls, video_path: Path) -> Path:
        video = Path(video_path).resolve()
        base = cls._numbered_screenshot_base(video.stem)
        highest = 0
        pattern = re.compile(rf"^{re.escape(base)}-(\d+)$")

        for sibling in video.parent.iterdir():
            if not sibling.is_file():
                continue
            if sibling.stem == base:
                highest = max(highest, 0)
                continue
            match = pattern.match(sibling.stem)
            if match:
                highest = max(highest, int(match.group(1)))

        return video.parent / f"{base}-{highest + 1}.png"

    def save_video_frame_png(self, video_path: Path, png_data: bytes) -> Path:
        video = Path(video_path).resolve()
        if not video.is_file():
            raise FileNotFoundError("找不到影片檔案")
        if not png_data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("圖片資料不是有效的 PNG")

        target = self.build_next_video_frame_path(video)
        target.write_bytes(png_data)
        self.store.clear_cache()
        return target.resolve()

    def create_folder(self, parent_path: Path, name: str) -> Path:
        if not self.is_valid_folder_basename(name):
            raise ValueError("名稱無效")
        parent = Path(parent_path).resolve()
        if not parent.is_dir():
            raise FileNotFoundError("父資料夾不存在")
        new_path = parent / name.strip()
        if new_path.exists():
            raise FileExistsError("已存在同名項目")
        new_path.mkdir(parents=False, exist_ok=False)
        self.store.invalidate_folder_cache(parent)
        self.store.invalidate_folder_cache(new_path)
        return new_path

    def rename_folder(self, folder_path: Path, new_name: str) -> Path:
        folder = Path(folder_path).resolve()
        root = self.store.ensure_root_folder()
        if folder == root.resolve():
            raise ValueError("不可重新命名主資料夾")
        if not self.is_valid_folder_basename(new_name):
            raise ValueError("名稱無效")
        new_name = new_name.strip()
        if new_name == folder.name:
            return folder
        new_path = folder.parent / new_name
        if new_path.exists():
            raise FileExistsError("已存在相同名稱的項目")
        try:
            old_rel = self.store.to_relative_key(folder)
        except Exception:
            old_rel = ""
        folder.rename(new_path)
        try:
            new_rel = self.store.to_relative_key(new_path)
        except Exception:
            new_rel = ""
        if old_rel and new_rel:
            self.tag_repo.rename_relative_path_root(old_rel, new_rel)
        self.store.clear_cache()
        return new_path

    def rename_file(self, file_path: Path, new_stem: str) -> Path:
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError("找不到檔案")
        if not self.is_valid_file_stem(new_stem):
            raise ValueError("主檔名無效")
        suffix = path.suffix
        new_path = path.parent / (new_stem.strip() + suffix)
        if new_path.resolve() == path:
            return path
        if new_path.exists():
            raise FileExistsError("已存在同名檔案")
        path.rename(new_path)
        self.store.invalidate_folder_cache(path.parent)
        return new_path

    def delete_folder(self, folder_path: Path) -> int:
        root = self.store.root_folder
        folder = Path(folder_path).resolve()
        if root and folder == Path(root).resolve():
            raise ValueError("不可刪除主資料夾")
        file_count = self.store.delete_folder(folder)
        try:
            relative_prefix = self.store.to_relative_key(folder)
        except Exception:
            relative_prefix = ""
        if relative_prefix:
            self.tag_repo.remove_keys_by_prefix(relative_prefix)
        return file_count

    def delete_files(self, file_paths: list[Path]) -> tuple[int, int]:
        deleted = 0
        failed = 0
        touched_parents: set[Path] = set()
        for fp in file_paths:
            path = Path(fp).resolve()
            if not path.is_file():
                failed += 1
                continue
            try:
                path.unlink()
                deleted += 1
                touched_parents.add(path.parent)
            except OSError:
                failed += 1
        for parent in touched_parents:
            self.store.invalidate_folder_cache(parent)
        return deleted, failed

    def transfer_folder_content(self, source_folder: Path, target_folder: Path) -> dict:
        src = Path(source_folder).resolve()
        dst = Path(target_folder).resolve()
        moved_count, renamed_count, source_deleted = self.store.move_folder_content_and_remove_source(src, dst)
        try:
            relative_key = self.store.to_relative_key(src)
        except Exception:
            relative_key = ""
        if relative_key:
            source_tags = self.tag_repo.get_tags(relative_key)
            self.tag_repo.remove_key(relative_key)
            try:
                target_key = self.store.to_relative_key(dst)
            except Exception:
                target_key = ""
            if source_tags and target_key:
                self.tag_repo.set_tags(target_key, self.tag_repo.get_tags(target_key) + source_tags)
        return {
            "moved_count": moved_count,
            "renamed_count": renamed_count,
            "source_deleted": source_deleted,
        }

    def transfer_files(self, file_paths: list[Path], target_folder: Path) -> dict:
        target = Path(target_folder).resolve()
        if not target.is_dir():
            raise FileNotFoundError("目標資料夾不存在")
        moved_count = 0
        renamed_count = 0
        skipped_same_folder = 0
        failed_count = 0
        touched_parents: set[Path] = set()
        for fp in file_paths:
            src = Path(fp).resolve()
            if not src.is_file():
                failed_count += 1
                continue
            if src.parent == target:
                skipped_same_folder += 1
                continue
            dst = target / src.name
            if dst.exists():
                dst = self.build_non_conflict_file_path(target, src.name)
                renamed_count += 1
            try:
                shutil.move(str(src), str(dst))
                moved_count += 1
                touched_parents.add(src.parent)
            except Exception:
                failed_count += 1
        for parent in touched_parents:
            self.store.invalidate_folder_cache(parent)
        self.store.invalidate_folder_cache(target)
        return {
            "moved_count": moved_count,
            "renamed_count": renamed_count,
            "skipped_same_folder": skipped_same_folder,
            "failed_count": failed_count,
        }

    def _validate_merge_folders(self, folder_paths: list[Path]) -> list[Path]:
        folders = [Path(p).resolve() for p in folder_paths]
        if len(folders) < 2:
            raise ValueError("請至少選擇兩個資料夾")
        if len(set(folders)) != len(folders):
            raise ValueError("選取資料夾不可重複")

        root = self.store.ensure_root_folder().resolve()
        for folder in folders:
            if not folder.is_dir():
                raise FileNotFoundError(f"資料夾不存在：{folder}")
            if folder == root:
                raise ValueError("不可合併主資料夾")

        for index, folder in enumerate(folders):
            for other in folders[index + 1:]:
                if folder.is_relative_to(other) or other.is_relative_to(folder):
                    raise ValueError("不可同時選取父資料夾與其子資料夾進行合併")
        return folders

    def find_folder_merge_conflicts(self, folder_paths: list[Path]) -> list[dict[str, str]]:
        folders = self._validate_merge_folders(folder_paths)
        target = folders[0]
        occupied: dict[tuple[str, ...], str] = {}
        conflicts: list[dict[str, str]] = []

        for item in target.rglob("*"):
            relative = item.relative_to(target).parts
            occupied[relative] = "dir" if item.is_dir() else "file"

        for source in folders[1:]:
            for item in sorted(source.rglob("*"), key=lambda p: str(p.relative_to(source)).casefold()):
                relative = item.relative_to(source).parts
                kind = "dir" if item.is_dir() else "file"
                existing_kind = occupied.get(relative)
                if existing_kind is not None and not (kind == "dir" and existing_kind == "dir"):
                    conflicts.append({
                        "source_path": str(item.resolve()),
                        "target_path": str((target / Path(*relative)).resolve()),
                        "name": item.name,
                    })
                    continue
                occupied.setdefault(relative, kind)
        return conflicts

    def _merge_folder_tags(self, old_folder: Path, new_folder: Path) -> None:
        try:
            old_rel = self.store.to_relative_key(old_folder)
            new_rel = self.store.to_relative_key(new_folder)
        except Exception:
            return
        if old_rel and new_rel:
            self.tag_repo.rename_relative_path_root(old_rel, new_rel)

    def merge_selected_folders(self, folder_paths: list[Path], conflict_strategy: str) -> dict:
        if conflict_strategy not in {"keep", "skip"}:
            raise ValueError("衝突處理策略無效")

        folders = self._validate_merge_folders(folder_paths)
        target = folders[0]
        moved_count = 0
        renamed_count = 0
        skipped_count = 0
        deleted_sources: list[Path] = []

        def move_or_merge(source_dir: Path, target_dir: Path) -> None:
            nonlocal moved_count, renamed_count, skipped_count
            target_dir.mkdir(parents=True, exist_ok=True)

            for item in sorted(source_dir.iterdir(), key=lambda p: p.name.lower()):
                candidate = target_dir / item.name
                if item.is_dir():
                    if not candidate.exists():
                        shutil.move(str(item), str(candidate))
                        moved_count += self._count_files(candidate)
                        self._merge_folder_tags(item, candidate)
                        continue

                    if candidate.is_dir():
                        move_or_merge(item, candidate)
                        continue

                    if conflict_strategy == "skip":
                        skipped_count += self._count_files(item)
                        continue

                    renamed_target = self.build_parenthesized_non_conflict_path(target_dir, item.name)
                    shutil.move(str(item), str(renamed_target))
                    moved_count += self._count_files(renamed_target)
                    renamed_count += 1
                    self._merge_folder_tags(item, renamed_target)
                    continue

                if not item.is_file():
                    continue

                if candidate.exists():
                    if conflict_strategy == "skip":
                        skipped_count += 1
                        continue
                    candidate = self.build_parenthesized_non_conflict_path(target_dir, item.name)
                    renamed_count += 1

                shutil.move(str(item), str(candidate))
                moved_count += 1

            try:
                source_dir.rmdir()
                self._merge_folder_tags(source_dir, target_dir)
            except OSError:
                pass

        for source in folders[1:]:
            move_or_merge(source, target)
            if not source.exists():
                deleted_sources.append(source)

        self.store.clear_cache()
        return {
            "target_folder": str(target),
            "moved_count": moved_count,
            "renamed_count": renamed_count,
            "skipped_count": skipped_count,
            "deleted_count": len(deleted_sources),
            "deleted_sources": [str(path) for path in deleted_sources],
        }

    def build_numbered_plan(
        self,
        old_paths: list[Path],
        base: str,
        start_no: int,
        *,
        is_folder: bool,
        allow_overwrite: bool = False,
    ) -> list[tuple[Path, Path]]:
        selected_set = {p.resolve() for p in old_paths}
        selected_parent_map: dict[Path, set[Path]] = {}
        for p in selected_set:
            selected_parent_map.setdefault(p.parent, set()).add(p)
        planned_targets: set[Path] = set()
        planned_file_stems: dict[Path, set[str]] = {}
        plan: list[tuple[Path, Path]] = []
        counter = start_no
        for old in old_paths:
            old = old.resolve()
            suffix = "" if is_folder else old.suffix
            while True:
                candidate = (old.parent / f"{base}-{counter}{suffix}").resolve()
                occupied_by_other = candidate.exists() and candidate not in selected_set
                if allow_overwrite and not is_folder:
                    occupied_by_other = False
                occupied_in_plan = candidate in planned_targets
                stem = candidate.stem
                stem_conflict = False
                if not is_folder:
                    siblings = []
                    try:
                        siblings = list(old.parent.iterdir())
                    except Exception:
                        siblings = []
                    selected_in_parent = selected_parent_map.get(old.parent, set())
                    existing_same_stem_other = any(
                        s.is_file() and s.stem == stem and s.resolve() not in selected_in_parent for s in siblings
                    )
                    planned_same_stem = stem in planned_file_stems.get(old.parent, set())
                    stem_conflict = planned_same_stem if allow_overwrite else existing_same_stem_other or planned_same_stem
                if not occupied_by_other and not occupied_in_plan:
                    if not stem_conflict or (candidate == old and stem == old.stem):
                        plan.append((old, candidate))
                        planned_targets.add(candidate)
                        if not is_folder:
                            planned_file_stems.setdefault(old.parent, set()).add(stem)
                        counter += 1
                        break
                if candidate == old:
                    plan.append((old, candidate))
                    planned_targets.add(candidate)
                    if not is_folder:
                        planned_file_stems.setdefault(old.parent, set()).add(stem)
                    counter += 1
                    break
                counter += 1
        return plan

    def apply_rename_plan(
        self,
        plan: list[tuple[Path, Path]],
        *,
        is_folder: bool,
        allow_overwrite: bool = False,
    ) -> list[tuple[str, str]]:
        old_new_rel_pairs: list[tuple[str, str]] = []
        tmp_plan: list[tuple[Path, Path, Path]] = []
        overwritten_plan: list[tuple[Path, Path]] = []
        touched_parents: set[Path] = set()
        try:
            for old, new in plan:
                if old == new:
                    continue
                touched_parents.add(old.parent)
                touched_parents.add(new.parent)
                if is_folder:
                    try:
                        old_rel = self.store.to_relative_key(old)
                        new_rel = self.store.to_relative_key(new)
                        old_new_rel_pairs.append((old_rel, new_rel))
                    except Exception:
                        pass
                tmp = self._unique_temp_path(old)
                old.rename(tmp)
                tmp_plan.append((tmp, old, new))
            tmp_paths = {tmp.resolve() for tmp, _old, _new in tmp_plan}
            for tmp, _old, new in tmp_plan:
                if allow_overwrite and not is_folder:
                    conflicts: list[Path] = []
                    if new.exists() and new.resolve() not in tmp_paths:
                        conflicts.append(new)
                    try:
                        conflicts.extend(
                            sibling
                            for sibling in new.parent.iterdir()
                            if sibling.is_file()
                            and sibling.stem == new.stem
                            and sibling.resolve() != new.resolve()
                            and sibling.resolve() not in tmp_paths
                        )
                    except OSError:
                        pass
                    for conflict in conflicts:
                        if not conflict.exists():
                            continue
                        if not conflict.is_file():
                            raise FileExistsError(f"目標不是檔案，無法覆蓋：{conflict}")
                        backup = self._unique_temp_path(conflict)
                        conflict.rename(backup)
                        overwritten_plan.append((backup, conflict))
                tmp.rename(new)
        except Exception as exc:
            for tmp, old, _new in reversed(tmp_plan):
                try:
                    if tmp.exists() and not old.exists():
                        tmp.rename(old)
                except Exception:
                    pass
            for backup, original in reversed(overwritten_plan):
                try:
                    if backup.exists() and not original.exists():
                        backup.rename(original)
                except Exception:
                    pass
            raise exc
        for backup, _original in overwritten_plan:
            try:
                if backup.exists():
                    backup.unlink()
            except Exception:
                pass
        if is_folder:
            for old_rel, new_rel in old_new_rel_pairs:
                if old_rel and new_rel:
                    self.tag_repo.rename_relative_path_root(old_rel, new_rel)
            self.store.clear_cache()
        else:
            for parent in touched_parents:
                self.store.invalidate_folder_cache(parent)
        return old_new_rel_pairs

    def open_path_external(self, path: Path) -> None:
        import subprocess
        import sys

        p = Path(path).resolve()
        if sys.platform.startswith("win"):
            import os
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)
