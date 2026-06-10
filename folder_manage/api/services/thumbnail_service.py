from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from api.constants import (
    ENTRY_THUMBNAIL_SIZE,
    MEDIA_THUMBNAIL_SIZE,
    THUMB_INDEX_FLUSH_CHANGE_COUNT,
    THUMB_INDEX_FLUSH_INTERVAL_SECONDS,
)
from app_paths import get_app_data_dir
from people_data_store import SubfolderEntry

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None


def _subprocess_hide_window_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


class ThumbnailService:
    def __init__(self, app_name: str, max_cache_size: int = 250):
        self.ffmpeg_path = self._resolve_ffmpeg_path()
        self.ffprobe_path = shutil.which("ffprobe")
        self.max_cache_size = max_cache_size
        self.cache_dir = get_app_data_dir(app_name) / "thumbnail_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / "thumb_index.json"
        self._cache_lock = threading.Lock()
        self._index_lock = threading.Lock()
        self._memory_cache: dict[str, Image.Image] = {}
        self._cache_order: list[str] = []
        self._video_duration_cache: dict[str, Optional[float]] = {}
        self._video_semaphore = threading.Semaphore(2)
        self._disk_index = self._load_disk_index()
        self._disk_index_dirty = False
        self._disk_index_pending_changes = 0
        self._last_disk_index_save_at = time.monotonic()

    def _resolve_ffmpeg_path(self) -> Optional[str]:
        from_system = shutil.which("ffmpeg")
        if from_system:
            return from_system
        if imageio_ffmpeg is not None:
            try:
                return imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                return None
        return None

    def _load_disk_index(self) -> dict:
        if not self.index_path.exists():
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    def _save_disk_index(self, *, force: bool = False) -> None:
        payload = ""
        with self._index_lock:
            if not force and not self._disk_index_dirty:
                return
            payload = json.dumps(self._disk_index, ensure_ascii=False)
            self._disk_index_dirty = False
            self._disk_index_pending_changes = 0
            self._last_disk_index_save_at = time.monotonic()
        try:
            self.index_path.write_text(payload, encoding="utf-8")
        except Exception:
            with self._index_lock:
                self._disk_index_dirty = True

    def flush_disk_index(self) -> None:
        self._save_disk_index(force=True)

    def _remember_disk_index_record(self, cache_key: str, cached_file: Path) -> None:
        now = time.monotonic()
        with self._index_lock:
            self._disk_index[cache_key] = {
                "cached_file": str(cached_file),
                "source_mtime": self._extract_source_mtime_from_key(cache_key),
            }
            self._disk_index_dirty = True
            self._disk_index_pending_changes += 1
            should_flush = (
                self._disk_index_pending_changes >= THUMB_INDEX_FLUSH_CHANGE_COUNT
                or now - self._last_disk_index_save_at >= THUMB_INDEX_FLUSH_INTERVAL_SECONDS
            )
        if should_flush:
            self._save_disk_index()

    def _remember_memory_cache(self, key: str, image: Image.Image) -> None:
        if key in self._memory_cache:
            self._cache_order.remove(key)
        self._memory_cache[key] = image.copy()
        self._cache_order.append(key)
        while len(self._cache_order) > self.max_cache_size:
            stale = self._cache_order.pop(0)
            self._memory_cache.pop(stale, None)

    def _build_file_cache_key(self, file_path: Path, media_type: str, size: tuple[int, int]) -> str:
        try:
            mtime = file_path.stat().st_mtime
        except Exception:
            mtime = 0
        return f"{media_type}::{file_path.resolve()}::{mtime}::{size[0]}x{size[1]}"

    def _extract_source_mtime_from_key(self, key: str) -> float:
        parts = key.split("::")
        if len(parts) >= 3:
            try:
                return float(parts[2])
            except Exception:
                return 0.0
        return 0.0

    def _load_from_disk_cache(self, cache_key: str, source_path: Path) -> Optional[Image.Image]:
        with self._index_lock:
            record = self._disk_index.get(cache_key)
        if not isinstance(record, dict):
            return None
        cached_file = Path(record.get("cached_file", ""))
        if not cached_file.exists():
            return None
        try:
            current_mtime = source_path.stat().st_mtime
        except Exception:
            current_mtime = 0
        cached_mtime = float(record.get("source_mtime", 0.0))
        if abs(current_mtime - cached_mtime) > 0.000001:
            return None
        try:
            with Image.open(cached_file) as src:
                return src.convert("RGB")
        except Exception:
            return None

    def _save_to_disk_cache(self, cache_key: str, image: Image.Image) -> None:
        cached_file = self.cache_dir / f"{hashlib.sha256(cache_key.encode('utf-8')).hexdigest()}.jpg"
        try:
            image.save(cached_file, format="JPEG", quality=88)
            self._remember_disk_index_record(cache_key, cached_file)
        except Exception:
            return

    def get_file_thumbnail(self, file_path: Path, media_type: str, size: tuple[int, int]) -> Image.Image:
        cache_key = self._build_file_cache_key(file_path, media_type, size)
        with self._cache_lock:
            cached = self._memory_cache.get(cache_key)
            if cached is not None:
                return cached.copy()

        image = self._load_from_disk_cache(cache_key, file_path)
        if image is None:
            if media_type == "image":
                image = self._build_image_thumbnail(file_path, size)
            elif media_type == "video":
                image = self._build_video_thumbnail(file_path, size)
            else:
                image = self._build_placeholder("UNKNOWN", size)
            self._save_to_disk_cache(cache_key, image)

        with self._cache_lock:
            self._remember_memory_cache(cache_key, image)
        return image.copy()

    def get_entry_thumbnail(self, entry: SubfolderEntry) -> Image.Image:
        if entry.preview_path and entry.preview_type:
            return self.get_file_thumbnail(entry.preview_path, entry.preview_type, ENTRY_THUMBNAIL_SIZE)
        return self._build_placeholder("NO MEDIA", ENTRY_THUMBNAIL_SIZE)

    def get_media_thumbnail(self, file_path: Path, media_type: str) -> Image.Image:
        return self.get_file_thumbnail(file_path, media_type, MEDIA_THUMBNAIL_SIZE)

    def _build_image_thumbnail(self, image_path: Path, size: tuple[int, int]) -> Image.Image:
        try:
            with Image.open(image_path) as src:
                return self._fit_image(src.convert("RGB"), size)
        except Exception:
            return self._build_placeholder("IMAGE ERR", size)

    def _build_video_thumbnail(self, video_path: Path, size: tuple[int, int]) -> Image.Image:
        if not self.ffmpeg_path:
            return self._build_placeholder("VIDEO", size)

        target_file = self.cache_dir / f"{self._hash_path(video_path)}_video.jpg"
        if not target_file.exists() or target_file.stat().st_size == 0:
            with self._video_semaphore:
                ok = self._extract_video_frame_with_fallback(video_path, target_file)
                if not ok:
                    return self._build_placeholder("VIDEO", size)

        return self._build_image_thumbnail(target_file, size)

    def _extract_video_frame_with_fallback(self, video_path: Path, output_file: Path) -> bool:
        offsets = self._build_video_offsets(video_path)
        for offset in offsets:
            if output_file.exists():
                try:
                    output_file.unlink()
                except Exception:
                    pass
            command = [
                self.ffmpeg_path,
                "-y",
                "-ss",
                offset,
                "-i",
                str(video_path),
                "-vf",
                "thumbnail",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(output_file),
            ]
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **_subprocess_hide_window_kwargs(),
            )
            if result.returncode == 0 and output_file.exists() and output_file.stat().st_size > 0:
                return True
        return False

    def _probe_duration_seconds(self, video_path: Path) -> Optional[float]:
        if not self.ffprobe_path:
            return None
        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            **_subprocess_hide_window_kwargs(),
        )
        if result.returncode != 0:
            return None
        try:
            value = float((result.stdout or "").strip())
        except Exception:
            return None
        return value if value > 0 else None

    def _probe_duration_via_ffmpeg_stderr(self, video_path: Path) -> Optional[float]:
        if not self.ffmpeg_path:
            return None
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-hide_banner", "-i", str(video_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                check=False,
                **_subprocess_hide_window_kwargs(),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        m = re.search(r"Duration:\s*(\d{1,2}):(\d{2}):(\d{2}\.\d+)", result.stderr or "")
        if not m:
            return None
        try:
            h = int(m.group(1))
            mi = int(m.group(2))
            sec = float(m.group(3))
        except ValueError:
            return None
        total = h * 3600 + mi * 60 + sec
        return total if total > 0 else None

    def _video_duration_cache_key(self, video_path: Path) -> str:
        return self._build_file_cache_key(video_path, "video_duration", (0, 0))

    def _remember_video_duration(self, cache_key: str, duration: Optional[float]) -> None:
        with self._cache_lock:
            self._video_duration_cache[cache_key] = duration
            if len(self._video_duration_cache) > self.max_cache_size * 6:
                stale_key = next(iter(self._video_duration_cache.keys()), None)
                if stale_key is not None:
                    self._video_duration_cache.pop(stale_key, None)

    def get_video_duration_seconds(self, video_path: Path) -> Optional[float]:
        cache_key = self._video_duration_cache_key(video_path)
        with self._cache_lock:
            if cache_key in self._video_duration_cache:
                return self._video_duration_cache[cache_key]

        d = self._probe_duration_seconds(video_path)
        if d is not None:
            self._remember_video_duration(cache_key, d)
            return d
        d = self._probe_duration_via_ffmpeg_stderr(video_path)
        self._remember_video_duration(cache_key, d)
        return d

    @staticmethod
    def format_video_duration(seconds: float) -> str:
        if seconds <= 0 or seconds != seconds:
            return "—"
        total = int(round(seconds))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _build_video_offsets(self, video_path: Path) -> list[str]:
        duration = self.get_video_duration_seconds(video_path)
        if duration is None or duration <= 0:
            return ["00:00:00.300", "00:00:01.000", "00:00:02.000", "00:00:03.500"]
        points = [
            max(0.2, duration * 0.05),
            max(0.5, duration * 0.15),
            max(1.0, duration * 0.35),
            max(1.5, duration * 0.60),
        ]
        return [self._format_seconds(x) for x in points]

    def _format_seconds(self, seconds: float) -> str:
        total_ms = max(0, int(seconds * 1000))
        h = total_ms // 3_600_000
        total_ms %= 3_600_000
        m = total_ms // 60_000
        total_ms %= 60_000
        s = total_ms // 1000
        ms = total_ms % 1000
        return f"{h:02}:{m:02}:{s:02}.{ms:03}"

    def _hash_path(self, path: Path) -> str:
        token = str(path.resolve())
        try:
            token += f"::{path.stat().st_mtime}"
        except Exception:
            pass
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _fit_image(self, image: Image.Image, size: tuple[int, int]) -> Image.Image:
        canvas = Image.new("RGB", size, "#f3f4f6")
        copy = image.copy()
        copy.thumbnail(size, Image.Resampling.LANCZOS)
        x = (size[0] - copy.width) // 2
        y = (size[1] - copy.height) // 2
        canvas.paste(copy, (x, y))
        return canvas

    def _build_placeholder(self, text: str, size: tuple[int, int]) -> Image.Image:
        image = Image.new("RGB", size, "#f3f4f6")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline="#e5e7eb", width=1)
        draw.text((14, size[1] // 2 - 6), text, fill="#6b7280")
        return image
