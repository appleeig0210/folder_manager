from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional

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

    def build_numbered_plan(
        self,
        old_paths: list[Path],
        base: str,
        start_no: int,
        *,
        is_folder: bool,
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
                    stem_conflict = existing_same_stem_other or planned_same_stem
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

    def apply_rename_plan(self, plan: list[tuple[Path, Path]], *, is_folder: bool) -> list[tuple[str, str]]:
        old_new_rel_pairs: list[tuple[str, str]] = []
        tmp_plan: list[tuple[Path, Path, Path]] = []
        try:
            for old, new in plan:
                if old == new:
                    continue
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
            for tmp, _old, new in tmp_plan:
                tmp.rename(new)
        except Exception as exc:
            for tmp, old, _new in reversed(tmp_plan):
                try:
                    if tmp.exists() and not old.exists():
                        tmp.rename(old)
                except Exception:
                    pass
            raise exc
        if is_folder:
            for old_rel, new_rel in old_new_rel_pairs:
                if old_rel and new_rel:
                    self.tag_repo.rename_relative_path_root(old_rel, new_rel)
            self.store.clear_cache()
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
