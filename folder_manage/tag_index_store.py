from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class TagIndexStore:
    _MISS = object()

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media_tags (
                    path TEXT PRIMARY KEY,
                    mtime_ns INTEGER NOT NULL,
                    tags_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM index_meta WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO index_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def clear_all(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM media_tags")
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM media_tags").fetchone()
        return int(row["c"]) if row else 0

    @staticmethod
    def _norm_path(path: Path | str) -> str:
        return str(Path(path).resolve())

    @staticmethod
    def _prefix_pattern(prefix: Path | str) -> str:
        base = TagIndexStore._norm_path(prefix)
        if not base.endswith("\\") and not base.endswith("/"):
            base = f"{base}{Path(base).anchor and '/' or '/'}"
        # Use forward slashes for consistent LIKE matching on all platforms.
        base = base.replace("\\", "/")
        if not base.endswith("/"):
            base = f"{base}/"
        return f"{base.replace('%', '\\%').replace('_', '\\_')}%"

    def get_batch(
        self,
        paths: list[Path],
        *,
        mtimes: dict[str, int] | None = None,
    ) -> tuple[dict[str, list[str]], list[Path]]:
        hits: dict[str, list[str]] = {}
        misses: list[Path] = []
        if not paths:
            return hits, misses

        keys = [self._norm_path(path) for path in paths]
        placeholders = ",".join("?" for _ in keys)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT path, mtime_ns, tags_json FROM media_tags WHERE path IN ({placeholders})",
                keys,
            ).fetchall()

        row_map = {str(row["path"]): row for row in rows}
        for raw in paths:
            path = Path(raw).resolve()
            key = str(path)
            row = row_map.get(key)
            if row is None:
                misses.append(path)
                continue
            expected_mtime = mtimes.get(key) if mtimes else None
            if expected_mtime is None:
                try:
                    expected_mtime = path.stat().st_mtime_ns
                except OSError:
                    misses.append(path)
                    continue
            if int(row["mtime_ns"]) != int(expected_mtime):
                misses.append(path)
                continue
            try:
                tags = json.loads(row["tags_json"])
            except json.JSONDecodeError:
                misses.append(path)
                continue
            if not isinstance(tags, list):
                misses.append(path)
                continue
            hits[key] = [str(t) for t in tags if str(t).strip()]
        return hits, misses

    def put_batch(self, entries: dict[str, tuple[int, list[str]]]) -> None:
        if not entries:
            return
        rows = [
            (path, int(mtime_ns), json.dumps(list(tags), ensure_ascii=False))
            for path, (mtime_ns, tags) in entries.items()
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO media_tags(path, mtime_ns, tags_json) VALUES(?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET mtime_ns = excluded.mtime_ns, tags_json = excluded.tags_json",
                rows,
            )
            self._conn.commit()

    def delete_path(self, path: Path | str) -> None:
        key = self._norm_path(path)
        with self._lock:
            self._conn.execute("DELETE FROM media_tags WHERE path = ?", (key,))
            self._conn.commit()

    def delete_paths(self, paths: list[Path | str]) -> None:
        if not paths:
            return
        keys = [self._norm_path(path) for path in paths]
        placeholders = ",".join("?" for _ in keys)
        with self._lock:
            self._conn.execute(
                f"DELETE FROM media_tags WHERE path IN ({placeholders})",
                keys,
            )
            self._conn.commit()

    def rename_path(self, old_path: Path | str, new_path: Path | str) -> None:
        old_key = self._norm_path(old_path)
        new_key = self._norm_path(new_path)
        with self._lock:
            row = self._conn.execute(
                "SELECT mtime_ns, tags_json FROM media_tags WHERE path = ?",
                (old_key,),
            ).fetchone()
            if row is None:
                return
            self._conn.execute("DELETE FROM media_tags WHERE path = ?", (old_key,))
            self._conn.execute(
                "INSERT INTO media_tags(path, mtime_ns, tags_json) VALUES(?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET mtime_ns = excluded.mtime_ns, tags_json = excluded.tags_json",
                (new_key, int(row["mtime_ns"]), row["tags_json"]),
            )
            self._conn.commit()

    def rename_prefix(self, old_prefix: Path | str, new_prefix: Path | str) -> None:
        old_base = self._norm_path(old_prefix).replace("\\", "/").rstrip("/")
        new_base = self._norm_path(new_prefix).replace("\\", "/").rstrip("/")
        if old_base == new_base:
            return
        with self._lock:
            rows = self._conn.execute("SELECT path, mtime_ns, tags_json FROM media_tags").fetchall()
            old_keys: list[str] = []
            new_rows: list[tuple[str, int, str]] = []
            for row in rows:
                old_path = str(row["path"])
                old_norm = old_path.replace("\\", "/")
                if old_norm != old_base and not old_norm.startswith(f"{old_base}/"):
                    continue
                suffix = old_norm[len(old_base) :].lstrip("/")
                new_norm = new_base if not suffix else f"{new_base}/{suffix}"
                new_path = new_norm.replace("/", "\\") if "\\" in old_path else new_norm
                old_keys.append(old_path)
                new_rows.append((new_path, int(row["mtime_ns"]), row["tags_json"]))
            if not old_keys:
                return
            placeholders = ",".join("?" for _ in old_keys)
            self._conn.execute(
                f"DELETE FROM media_tags WHERE path IN ({placeholders})",
                old_keys,
            )
            self._conn.executemany(
                "INSERT INTO media_tags(path, mtime_ns, tags_json) VALUES(?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET mtime_ns = excluded.mtime_ns, tags_json = excluded.tags_json",
                new_rows,
            )
            self._conn.commit()

    def paths_under_prefix(self, prefix: Path | str) -> set[str]:
        prefix_like = self._prefix_pattern(prefix)
        prefix_norm = self._norm_path(prefix).replace("\\", "/")
        with self._lock:
            rows = self._conn.execute(
                "SELECT path FROM media_tags WHERE replace(path, '\\', '/') LIKE ? ESCAPE '\\' OR replace(path, '\\', '/') = ?",
                (prefix_like.replace("\\", "/"), prefix_norm),
            ).fetchall()
        return {str(row["path"]) for row in rows}

    def prune_missing(self, keep_paths: set[str]) -> int:
        if not keep_paths:
            return 0
        normalized_keep = {self._norm_path(path) for path in keep_paths}
        with self._lock:
            rows = self._conn.execute("SELECT path FROM media_tags").fetchall()
            stale = [str(row["path"]) for row in rows if str(row["path"]) not in normalized_keep]
            if not stale:
                return 0
            placeholders = ",".join("?" for _ in stale)
            self._conn.execute(
                f"DELETE FROM media_tags WHERE path IN ({placeholders})",
                stale,
            )
            self._conn.commit()
        return len(stale)

    def delete_under_prefix(self, prefix: Path | str) -> int:
        paths = self.paths_under_prefix(prefix)
        if not paths:
            return 0
        with self._lock:
            placeholders = ",".join("?" for _ in paths)
            self._conn.execute(
                f"DELETE FROM media_tags WHERE path IN ({placeholders})",
                list(paths),
            )
            self._conn.commit()
        return len(paths)

    def prune_orphans_under_prefixes(self, prefixes: list[Path], existing_paths: set[str]) -> int:
        indexed: set[str] = set()
        for prefix in prefixes:
            indexed.update(self.paths_under_prefix(prefix))
        stale = indexed - {self._norm_path(path) for path in existing_paths}
        if not stale:
            return 0
        with self._lock:
            placeholders = ",".join("?" for _ in stale)
            self._conn.execute(
                f"DELETE FROM media_tags WHERE path IN ({placeholders})",
                list(stale),
            )
            self._conn.commit()
        return len(stale)

    def prune_stale_files_under_prefixes(self, prefixes: list[Path]) -> int:
        """Remove index rows whose files no longer exist (no full disk walk)."""
        stale: list[str] = []
        for prefix in prefixes:
            for path_str in self.paths_under_prefix(prefix):
                try:
                    if not Path(path_str).is_file():
                        stale.append(path_str)
                except OSError:
                    stale.append(path_str)
        if not stale:
            return 0
        with self._lock:
            placeholders = ",".join("?" for _ in stale)
            self._conn.execute(
                f"DELETE FROM media_tags WHERE path IN ({placeholders})",
                stale,
            )
            self._conn.commit()
        return len(stale)

    def get_all_unique_tags(self) -> list[str]:
        merged: dict[str, str] = {}
        with self._lock:
            rows = self._conn.execute("SELECT tags_json FROM media_tags").fetchall()
        for row in rows:
            try:
                tags = json.loads(row["tags_json"])
            except json.JSONDecodeError:
                continue
            if not isinstance(tags, list):
                continue
            for tag in tags:
                clean = str(tag).strip()
                if not clean:
                    continue
                key = clean.casefold()
                if key not in merged:
                    merged[key] = clean
        return sorted(merged.values(), key=str.casefold)

    @staticmethod
    def _tags_match_any(tags: list[str], selected_keys: set[str]) -> bool:
        if not selected_keys:
            return True
        file_keys = {str(tag).strip().casefold() for tag in tags if str(tag).strip()}
        return bool(file_keys.intersection(selected_keys))

    def paths_with_any_tag(
        self,
        selected_tags: set[str],
        *,
        under_prefix: Path | str | None = None,
    ) -> set[str]:
        selected_keys = {(tag or "").strip().casefold() for tag in selected_tags if (tag or "").strip()}
        if not selected_keys:
            return set()
        prefix_norm = self._norm_path(under_prefix).replace("\\", "/") if under_prefix else None
        result: set[str] = set()
        with self._lock:
            if prefix_norm:
                prefix_like = self._prefix_pattern(under_prefix)
                rows = self._conn.execute(
                    "SELECT path, tags_json FROM media_tags "
                    "WHERE replace(path, '\\', '/') LIKE ? ESCAPE '\\' OR replace(path, '\\', '/') = ?",
                    (prefix_like.replace("\\", "/"), prefix_norm),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT path, tags_json FROM media_tags").fetchall()
        for row in rows:
            try:
                tags = json.loads(row["tags_json"])
            except json.JSONDecodeError:
                continue
            if not isinstance(tags, list):
                continue
            if self._tags_match_any([str(t) for t in tags], selected_keys):
                result.add(str(row["path"]))
        return result

    def paths_having_any_tag(self, tags: list[str]) -> list[str]:
        tokens = {(tag or "").strip().casefold() for tag in tags if (tag or "").strip()}
        if not tokens:
            return []
        matched: list[str] = []
        with self._lock:
            rows = self._conn.execute("SELECT path, tags_json FROM media_tags").fetchall()
        for row in rows:
            try:
                row_tags = json.loads(row["tags_json"])
            except json.JSONDecodeError:
                continue
            if not isinstance(row_tags, list):
                continue
            file_keys = {str(tag).strip().casefold() for tag in row_tags if str(tag).strip()}
            if file_keys.intersection(tokens):
                matched.append(str(row["path"]))
        return matched

    def folder_has_tagged_media(
        self,
        folder: Path,
        selected_tags: set[str],
        media_paths: list[Path],
    ) -> bool:
        if not selected_tags:
            return True
        if not media_paths:
            return False
        selected_keys = {(tag or "").strip().casefold() for tag in selected_tags if (tag or "").strip()}
        hits, misses = self.get_batch(media_paths)
        for tags in hits.values():
            if self._tags_match_any(tags, selected_keys):
                return True
        if misses:
            return False
        return False
