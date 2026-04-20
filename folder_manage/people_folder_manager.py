#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import sys
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from tkinter import filedialog, messagebox, simpledialog, ttk

from app_paths import get_app_data_dir, get_config_path
from people_data_store import MediaItem, PeopleDataStore, SubfolderEntry
from tag_repository import TagRepository

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES, COPY
except Exception:
    TkinterDnD = None
    DND_FILES = None
    COPY = None

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None


APP_NAME = "PeopleFolderManager"
ENTRY_THUMBNAIL_SIZE = (240, 170)
MEDIA_THUMBNAIL_SIZE = (240, 200)
ENTRY_CARD_SIZE = (280, 260)
MEDIA_CARD_SIZE = (280, 312)

ENTRY_COLUMNS = 5
MEDIA_COLUMNS = 5
ENTRY_BATCH_FIRST = 6
ENTRY_BATCH_SIZE = 12
MEDIA_BATCH_FIRST = 8
MEDIA_BATCH_SIZE = 16
THUMB_YVIEW_LOAD_THRESHOLD = 0.78
THUMB_YVIEW_DEBOUNCE_MS = 90

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


if TkinterDnD is not None:
    class _DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)


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

    def _save_disk_index(self) -> None:
        with self._index_lock:
            self.index_path.write_text(json.dumps(self._disk_index, ensure_ascii=False), encoding="utf-8")

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
            self._disk_index[cache_key] = {
                "cached_file": str(cached_file),
                "source_mtime": self._extract_source_mtime_from_key(cache_key),
            }
            self._save_disk_index()
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
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
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

    def get_video_duration_seconds(self, video_path: Path) -> Optional[float]:
        cache_key = self._build_file_cache_key(video_path, "video_duration", (0, 0))
        with self._cache_lock:
            if cache_key in self._video_duration_cache:
                return self._video_duration_cache[cache_key]

        d = self._probe_duration_seconds(video_path)
        if d is not None:
            with self._cache_lock:
                self._video_duration_cache[cache_key] = d
            return d
        d = self._probe_duration_via_ffmpeg_stderr(video_path)
        with self._cache_lock:
            self._video_duration_cache[cache_key] = d
            # Keep duration cache bounded to avoid unbounded memory growth.
            if len(self._video_duration_cache) > self.max_cache_size * 6:
                stale_key = next(iter(self._video_duration_cache.keys()), None)
                if stale_key is not None:
                    self._video_duration_cache.pop(stale_key, None)
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
        duration = self._probe_duration_seconds(video_path)
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


class PeopleFolderManagerApp:
    def __init__(self):
        self._dnd_available = False
        if TkinterDnD is not None:
            try:
                self.root = _DnDCTk()
                self._dnd_available = True
            except Exception:
                self.root = ctk.CTk()
        else:
            self.root = ctk.CTk()
        self.root.title("人物資料夾管理器")
        self.root.geometry("1760x920")

        self.config_path = get_config_path(APP_NAME)
        self.config = self._load_config()

        self.store = PeopleDataStore()
        self.tag_repo = TagRepository(APP_NAME)
        self.thumbnail_service = ThumbnailService(APP_NAME)
        self.scan_executor = ThreadPoolExecutor(max_workers=2)
        self.thumb_executor = ThreadPoolExecutor(max_workers=4)

        self.tree_metadata: dict[str, dict] = {}
        self.path_node_index: dict[str, str] = {}
        self.person_entries: dict[str, list[SubfolderEntry]] = {}
        self.current_entries: list[SubfolderEntry] = []
        self.current_media_items: list[MediaItem] = []
        self.current_scope_label = "未選擇"
        self.current_scope_path: Optional[Path] = None
        self.current_view_mode = "entries"
        self._thumb_paging_state: Optional[dict] = None
        self._thumb_scroll_hooked = False
        self._thumb_yview_after_id: Optional[str] = None
        self.current_subfolder_entry: Optional[SubfolderEntry] = None
        self.filter_vars: dict[str, ctk.BooleanVar] = {}
        self.selected_filter_tags: set[str] = set()
        self.filter_media_video_var = ctk.BooleanVar(value=False)
        self.filter_media_image_var = ctk.BooleanVar(value=False)
        self.filter_duration_min_var = ctk.StringVar(value="")
        self.filter_duration_max_var = ctk.StringVar(value="")
        self.filter_tags_expanded = True
        self._context_target: Optional[SubfolderEntry] = None
        self._context_media_item: Optional[MediaItem] = None
        self._active_media_browser: Optional["MediaBrowserWindow"] = None
        self.selected_entry_keys: set[str] = set()
        self.selected_media_paths: set[str] = set()
        self._entry_card_widgets: dict[str, ctk.CTkFrame] = {}
        self._media_card_widgets: dict[str, ctk.CTkFrame] = {}
        self._selection_anchor_index: Optional[int] = None
        self._drag_state: Optional[dict] = None
        self._drag_hint_win: Optional[tk.Toplevel] = None
        self._insert_indicator: Optional[tk.Frame] = None
        self._suppress_tree_select_once = False

        self.load_session_id = 0
        self.active_session_id = 0
        self.session_first_thumb_logged: dict[int, bool] = {}
        self.profile_enabled = True
        self.selection_debounce_ms = 120
        self._pending_select_after_id: Optional[str] = None
        self._pending_selected_item: Optional[str] = None
        self._ui_task_queue: queue.Queue = queue.Queue()
        self._ui_pump_pending = False
        self._tree_drag_source: Optional[str] = None
        self._tree_host: Optional[tk.Frame] = None
        self._tree_drag_start_xy: Optional[tuple[int, int]] = None
        self._tree_drop_line: Optional[tk.Frame] = None
        self._tree_drop_child_frame: Optional[tk.Frame] = None
        self._tree_drag_visual_active = False
        self._folder_media_filter_cache: dict[tuple[str, str], bool] = {}
        self.preview_sort_mode: str = "name"  # name | time | type
        self._preview_sort_menu: Optional[tk.Menu] = None

        self._init_visual_style()
        self._build_layout()
        self._apply_saved_root()
        self.refresh_tree()
        self.refresh_filter_panel()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    @staticmethod
    def _platform_font_family() -> str:
        if sys.platform.startswith("win"):
            return "Segoe UI"
        if sys.platform == "darwin":
            return "SF Pro Display"
        return "DejaVu Sans"

    def _init_visual_style(self) -> None:
        self.ui_colors = {
            "bg": "#f6f7fb",
            "panel": "#ffffff",
            "panel2": "#f9fafb",
            "border": "#e5e7eb",
            "text": "#111827",
            "muted": "#6b7280",
            "accent": "#2563eb",
            "accent_soft": "#dbeafe",
        }

        family = self._platform_font_family()
        self.font_base = ctk.CTkFont(family=family, size=12)
        self.font_base_bold = ctk.CTkFont(family=family, size=12, weight="bold")
        self.font_small = ctk.CTkFont(family=family, size=11)
        self.font_small_bold = ctk.CTkFont(family=family, size=11, weight="bold")
        self.font_title = ctk.CTkFont(family=family, size=13, weight="bold")
        self.font_icon = ctk.CTkFont(family=family, size=14, weight="bold")

        try:
            self.root.configure(fg_color=self.ui_colors["bg"])
        except Exception:
            pass

    def _load_config(self) -> dict:
        default = {"root_folder": "", "tree_child_order": {}}
        if self.config_path.exists():
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return {**default, **payload}
            except Exception:
                pass
        self._save_config(default)
        return default

    def _save_config(self, config: Optional[dict] = None) -> None:
        data = config if config is not None else self.config
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _apply_saved_root(self) -> None:
        root_folder = (self.config.get("root_folder") or "").strip()
        if not root_folder:
            return
        root_path = Path(root_folder)
        if root_path.exists() and root_path.is_dir():
            self.store.set_root_folder(root_path)
            self.root_dir_var.set(str(root_path))

    def _build_layout(self) -> None:
        top_frame = ctk.CTkFrame(self.root, fg_color=self.ui_colors["panel"])
        top_frame.pack(fill="x", padx=10, pady=(10, 6))

        ctk.CTkLabel(top_frame, text="主資料夾：", font=self.font_base_bold, text_color=self.ui_colors["text"]).pack(
            side="left", padx=(10, 4)
        )
        self.root_dir_var = ctk.StringVar(value="")
        self.root_dir_entry = ctk.CTkEntry(top_frame, textvariable=self.root_dir_var, width=620, font=self.font_base)
        self.root_dir_entry.pack(side="left", padx=4, pady=8)
        ctk.CTkButton(top_frame, text="選擇資料夾", width=100, command=self.choose_root_folder, font=self.font_base).pack(
            side="left", padx=4
        )
        ctk.CTkButton(top_frame, text="刷新", width=70, command=self.refresh_tree, font=self.font_base).pack(
            side="left", padx=4
        )
        ctk.CTkButton(top_frame, text="匯入 JSON", width=90, command=self.import_tags_json, font=self.font_base).pack(
            side="left", padx=(14, 4)
        )
        ctk.CTkButton(top_frame, text="匯入 CSV", width=90, command=self.import_tags_csv, font=self.font_base).pack(
            side="left", padx=4
        )
        ctk.CTkButton(top_frame, text="匯出 JSON", width=90, command=self.export_tags_json, font=self.font_base).pack(
            side="left", padx=(14, 4)
        )
        ctk.CTkButton(top_frame, text="匯出 CSV", width=90, command=self.export_tags_csv, font=self.font_base).pack(
            side="left", padx=4
        )

        body = ctk.CTkFrame(self.root, fg_color=self.ui_colors["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.tree_paned = tk.PanedWindow(
            body,
            orient=tk.HORIZONTAL,
            sashwidth=5,
            sashrelief=tk.FLAT,
            sashpad=2,
            bg=self.ui_colors["bg"],
            bd=0,
        )
        self.tree_paned.grid(row=0, column=0, sticky="nsew", padx=0, pady=8)

        left_frame = ctk.CTkFrame(self.tree_paned, corner_radius=10, fg_color=self.ui_colors["panel"])
        right_frame = ctk.CTkFrame(self.tree_paned, corner_radius=10, fg_color=self.ui_colors["panel"])
        self.tree_paned.add(left_frame, minsize=200, stretch="never")
        self.tree_paned.add(right_frame, minsize=520, stretch="always")

        ctk.CTkLabel(
            left_frame,
            text="導覽樹狀欄位（拖曳中間分隔線調整寬度）",
            font=self.font_base_bold,
            text_color=self.ui_colors["text"],
        ).pack(anchor="w", padx=12, pady=(12, 8))

        tree_host = tk.Frame(left_frame, bg=self.ui_colors["panel"])
        tree_host.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)
        self._tree_host = tree_host

        self.folder_tree = ttk.Treeview(tree_host, show="tree", selectmode="browse")
        self.folder_tree.grid(row=0, column=0, sticky="nsew")
        tree_vsb = ttk.Scrollbar(tree_host, orient="vertical", command=self.folder_tree.yview)
        tree_vsb.grid(row=0, column=1, sticky="ns")
        tree_hsb = ttk.Scrollbar(tree_host, orient="horizontal", command=self.folder_tree.xview)
        tree_hsb.grid(row=1, column=0, sticky="ew", columnspan=2)
        self.folder_tree.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            style.theme_use("default")
        style.configure(
            "Treeview",
            background=self.ui_colors["panel"],
            foreground=self.ui_colors["text"],
            fieldbackground=self.ui_colors["panel"],
            borderwidth=0,
            rowheight=24,
            font=(self._platform_font_family(), 11),
        )
        style.configure(
            "Treeview.Heading",
            background=self.ui_colors["panel2"],
            foreground=self.ui_colors["text"],
            borderwidth=0,
            font=(self._platform_font_family(), 11, "bold"),
        )
        style.map("Treeview", background=[("selected", self.ui_colors["accent_soft"])], foreground=[("selected", self.ui_colors["text"])])
        style.configure(
            "TScrollbar",
            troughcolor=self.ui_colors["panel2"],
            background=self.ui_colors["border"],
            bordercolor=self.ui_colors["panel2"],
            lightcolor=self.ui_colors["panel2"],
            darkcolor=self.ui_colors["panel2"],
            arrowsize=12,
        )

        self.folder_tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.folder_tree.bind("<<TreeviewOpen>>", self.on_tree_open)
        self.folder_tree.bind("<ButtonPress-1>", self._on_tree_drag_press, add=True)
        self.folder_tree.bind("<B1-Motion>", self._on_tree_drag_motion, add=True)
        self.root.bind("<ButtonRelease-1>", self._on_root_button1_release_tree_drag, add=True)
        self._bind_right_click_menu(self.folder_tree, self.on_tree_right_click)

        self.root.after_idle(self._set_initial_tree_pane_sash)

        right_frame.grid_rowconfigure(2, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        scope_row = ctk.CTkFrame(right_frame, fg_color="transparent")
        scope_row.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        scope_row.grid_columnconfigure(1, weight=1)
        self.back_up_button = ctk.CTkButton(
            scope_row, text="← 返回上一層", width=118, command=self.navigate_back_one_level, font=self.font_base
        )
        self.back_up_button.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.scope_label = ctk.CTkLabel(
            scope_row, text="目前檢視：未選擇", anchor="w", font=self.font_title, text_color=self.ui_colors["text"]
        )
        self.scope_label.grid(row=0, column=1, sticky="ew")

        filter_frame = ctk.CTkFrame(right_frame, fg_color=self.ui_colors["panel"])
        filter_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.filter_tags_header_frame = ctk.CTkFrame(filter_frame, fg_color="transparent")
        self.filter_tags_header_frame.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(
            self.filter_tags_header_frame,
            text="標籤篩選（勾選即套用 OR）",
            font=self.font_small_bold,
            text_color=self.ui_colors["text"],
        ).pack(side="left", padx=(0, 6))
        self.filter_tags_toggle_btn = ctk.CTkButton(
            self.filter_tags_header_frame,
            text="▼ 收合標籤",
            width=96,
            height=26,
            command=self.on_toggle_filter_tags,
            font=self.font_small,
        )
        self.filter_tags_toggle_btn.pack(side="right", padx=(8, 0))
        self.filter_tags_container = ctk.CTkScrollableFrame(filter_frame, height=96, fg_color=self.ui_colors["panel2"])
        self.filter_tags_container.pack(fill="x", padx=8, pady=(0, 6), after=self.filter_tags_header_frame)
        self.media_row_filter_frame = ctk.CTkFrame(filter_frame, fg_color="transparent")
        self.media_row_filter_frame.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(
            self.media_row_filter_frame, text="媒體類型：", font=self.font_small_bold, text_color=self.ui_colors["text"]
        ).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkCheckBox(
            self.media_row_filter_frame,
            text="影片",
            variable=self.filter_media_video_var,
            command=self.on_media_type_filter_changed,
            width=70,
            font=self.font_small,
        ).pack(side="left", padx=(0, 10))
        ctk.CTkCheckBox(
            self.media_row_filter_frame,
            text="圖片",
            variable=self.filter_media_image_var,
            command=self.on_media_type_filter_changed,
            width=70,
            font=self.font_small,
        ).pack(side="left", padx=(0, 14))
        ctk.CTkLabel(
            self.media_row_filter_frame, text="影片長度（分）", font=self.font_small_bold, text_color=self.ui_colors["text"]
        ).pack(
            side="left", padx=(0, 4)
        )
        self.filter_duration_min_entry = ctk.CTkEntry(
            self.media_row_filter_frame, textvariable=self.filter_duration_min_var, width=52, font=self.font_small
        )
        self.filter_duration_min_entry.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(self.media_row_filter_frame, text="～", font=self.font_small, text_color=self.ui_colors["muted"]).pack(
            side="left", padx=(0, 4)
        )
        self.filter_duration_max_entry = ctk.CTkEntry(
            self.media_row_filter_frame, textvariable=self.filter_duration_max_var, width=52, font=self.font_small
        )
        self.filter_duration_max_entry.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            self.media_row_filter_frame, text="套用", width=56, command=self.on_apply_duration_filter, font=self.font_small
        ).pack(
            side="left", padx=(0, 4)
        )
        for w in (self.filter_duration_min_entry, self.filter_duration_max_entry):
            w.bind("<Return>", self._on_duration_filter_return)

        self.thumbnail_scroll = ctk.CTkScrollableFrame(
            right_frame, label_text="子資料夾縮圖預覽", fg_color=self.ui_colors["panel2"]
        )
        self.thumbnail_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._ensure_thumbnail_scroll_hook()
        self._init_preview_sort_menu()

        status_frame = ctk.CTkFrame(self.root, fg_color=self.ui_colors["panel"])
        status_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.status_label = ctk.CTkLabel(
            status_frame, text="就緒", anchor="w", font=self.font_small, text_color=self.ui_colors["muted"]
        )
        self.status_label.pack(side="left", padx=10, pady=6)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="新增資料夾…", command=self.create_folder_under_current_target)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="添加標籤", command=self.add_tags_to_current_target)
        self.context_menu.add_command(label="打開目標資料夾", command=self.open_current_target_folder)
        self.context_menu.add_command(label="重新命名資料夾", command=self.rename_current_target_folder)
        self.context_menu.add_command(label="重新命名檔案", command=self.rename_current_target_file)
        self.context_menu.add_command(label="轉移資料夾內容到…", command=self.transfer_current_target_folder)
        self.context_menu.add_command(label="轉移已選取項目到…", command=self.transfer_selected_preview_items)
        self.context_menu.add_command(label="轉移並建立新資料夾…", command=self.transfer_selected_to_new_folder)
        self.context_menu.add_command(label="重新命名與添加序號…", command=self.rename_and_number_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="刪除選取的檔案或資料夾…", command=self.delete_selected_preview_items)
        self.context_menu.add_command(label="刪除資料夾", command=self.delete_current_target_folder)

    def _init_preview_sort_menu(self) -> None:
        if self._preview_sort_menu is not None:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="依名稱排序", command=lambda: self.set_preview_sort_mode("name"))
        menu.add_command(label="依時間排序", command=lambda: self.set_preview_sort_mode("time"))
        menu.add_command(label="依檔案類型排序", command=lambda: self.set_preview_sort_mode("type"))
        self._preview_sort_menu = menu

        def on_right_click_preview_bg(event: tk.Event) -> None:
            if self._preview_sort_menu is None:
                return
            try:
                self._preview_sort_menu.tk_popup(event.x_root, event.y_root)
            finally:
                try:
                    self._preview_sort_menu.grab_release()
                except Exception:
                    pass

        # Bind to preview background (canvas + scrollable frame). Cards themselves keep their own context menus.
        self._bind_right_click_menu(self.thumbnail_scroll, on_right_click_preview_bg)
        try:
            self._bind_right_click_menu(self.thumbnail_scroll._parent_canvas, on_right_click_preview_bg)
        except Exception:
            pass

    def set_preview_sort_mode(self, mode: str) -> None:
        mode = (mode or "").strip().lower()
        if mode not in {"name", "time", "type"}:
            return
        if self.preview_sort_mode == mode:
            return
        self.preview_sort_mode = mode
        label = {"name": "名稱", "time": "時間", "type": "檔案類型"}.get(mode, mode)
        self.set_status(f"預覽區排序：{label}")
        if self.current_view_mode == "media":
            self._render_media_from_current_items()
        else:
            self.render_entries(self.current_entries)

    def _sorted_entries_for_preview(self, entries: list[SubfolderEntry]) -> list[SubfolderEntry]:
        mode = self.preview_sort_mode
        if mode == "time":
            def key(e: SubfolderEntry):
                try:
                    return (Path(e.subfolder_path).stat().st_mtime, e.subfolder_name.lower())
                except Exception:
                    return (0.0, e.subfolder_name.lower())
            return sorted(entries, key=key, reverse=True)
        if mode == "type":
            def key(e: SubfolderEntry):
                t = (e.preview_type or "").lower()
                return (t, e.subfolder_name.lower())
            return sorted(entries, key=key)
        return sorted(entries, key=lambda e: e.subfolder_name.lower())

    def _sorted_media_for_preview(self, items: list[MediaItem]) -> list[MediaItem]:
        mode = self.preview_sort_mode
        if mode == "time":
            def key(m: MediaItem):
                try:
                    return (Path(m.media_path).stat().st_mtime, m.media_path.name.lower())
                except Exception:
                    return (0.0, m.media_path.name.lower())
            return sorted(items, key=key, reverse=True)
        if mode == "type":
            def key(m: MediaItem):
                ext = Path(m.media_path).suffix.lower()
                return (m.media_type, ext, m.media_path.name.lower())
            return sorted(items, key=key)
        return sorted(items, key=lambda m: m.media_path.name.lower())

    def _on_duration_filter_return(self, _event: tk.Event) -> str:
        self.on_apply_duration_filter()
        return "break"

    def _can_navigate_back(self) -> bool:
        if self.store.root_folder is None or self.current_scope_path is None:
            return False
        root = Path(self.store.root_folder).resolve()
        cur = Path(self.current_scope_path).resolve()
        return cur != root and root in [cur, *cur.parents]

    def _update_back_buttons_state(self) -> None:
        st = "normal" if self._can_navigate_back() else "disabled"
        try:
            self.back_up_button.configure(state=st)
        except Exception:
            pass

    def _reset_preview_scroll_top(self) -> None:
        try:
            self.thumbnail_scroll._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _try_sync_tree_selection(self, path_obj: Path) -> None:
        node_id = self.path_node_index.get(self._path_key(path_obj))
        if not node_id:
            return
        self._suppress_tree_select_once = True
        try:
            self.folder_tree.selection_set(node_id)
            self.folder_tree.focus(node_id)
            self.folder_tree.see(node_id)
        except Exception:
            self._suppress_tree_select_once = False

    def navigate_back_one_level(self) -> None:
        if not self._can_navigate_back() or self.current_scope_path is None:
            return
        root = Path(self.store.root_folder).resolve() if self.store.root_folder else None
        cur = Path(self.current_scope_path).resolve()
        parent = cur.parent
        if root is None:
            return
        self._try_sync_tree_selection(parent)
        if parent == root:
            self.current_scope_path = root
            self.current_scope_label = "全部人物"
            self._begin_load_merged_entries()
            self._update_back_buttons_state()
            return
        children = self._order_entries_by_saved_tree(parent, self.store.get_subfolder_entries_shallow(parent))
        self.current_scope_path = parent
        self.current_scope_label = parent.name
        self.render_entries(children)
        self._update_back_buttons_state()

    def _open_entry_from_preview(self, entry: SubfolderEntry) -> None:
        folder = Path(entry.subfolder_path).resolve()
        self._try_sync_tree_selection(folder)
        children = self._get_ordered_subfolders(folder)
        if children:
            entries = self._order_entries_by_saved_tree(folder, self.store.get_subfolder_entries_shallow(folder))
            self.current_scope_path = folder
            self.current_scope_label = folder.name
            self.render_entries(entries)
            self.set_status(f"進入資料夾：{folder.name}")
            return
        self.current_scope_path = folder
        self.current_scope_label = f"{entry.person_name} / {entry.subfolder_name}"
        self.render_subfolder_media(entry)

    def _set_initial_tree_pane_sash(self) -> None:
        try:
            self.root.update_idletasks()
            self.tree_paned.sash_place(0, 280, 0)
        except tk.TclError:
            pass

    def _new_session(self) -> int:
        self.load_session_id += 1
        self.active_session_id = self.load_session_id
        self.session_first_thumb_logged[self.active_session_id] = False
        return self.active_session_id

    def _is_active_session(self, sid: int) -> bool:
        return sid == self.active_session_id

    def _enqueue_ui_task(self, fn, *args, **kwargs) -> None:
        """ThreadPool 回呼在背景執行緒，不可直接呼叫 Tk；經佇列丟回主執行緒處理。"""
        self._ui_task_queue.put((fn, args, kwargs))
        if not self._ui_pump_pending:
            self._ui_pump_pending = True
            try:
                self.root.after(0, self._pump_ui_task_queue)
            except tk.TclError:
                self._ui_pump_pending = False

    def _pump_ui_task_queue(self) -> None:
        self._ui_pump_pending = False
        try:
            while True:
                fn, args, kwargs = self._ui_task_queue.get_nowait()
                try:
                    fn(*args, **kwargs)
                except tk.TclError:
                    pass
                except Exception:
                    pass
        except queue.Empty:
            pass
        if not self._ui_task_queue.empty():
            self._ui_pump_pending = True
            try:
                self.root.after(0, self._pump_ui_task_queue)
            except tk.TclError:
                self._ui_pump_pending = False

    def _perf_start(self) -> float:
        return time.perf_counter()

    def _perf_log(self, label: str, start_ts: float, extra: str = "") -> None:
        if not self.profile_enabled:
            return
        elapsed = (time.perf_counter() - start_ts) * 1000
        print(f"[PERF] {label}: {elapsed:.1f}ms{(' | ' + extra) if extra else ''}")

    def set_status(self, message: str) -> None:
        self.status_label.configure(text=message)

    def _bind_right_click_menu(self, widget, callback) -> None:
        """macOS 上次要鍵多為 Button-2；Windows／Linux 為 Button-3；觸控板可為 Control+左鍵。"""
        widget.bind("<Button-2>", callback)
        widget.bind("<Button-3>", callback)
        if sys.platform == "darwin":
            widget.bind("<Control-Button-1>", callback)

    def _snapshot_media_view(self) -> Optional[SubfolderEntry]:
        if self.current_view_mode == "media" and self.current_subfolder_entry is not None:
            return self.current_subfolder_entry
        return None

    def _restore_media_view_if_needed(self, entry: Optional[SubfolderEntry]) -> None:
        if entry is None:
            return
        if not self.selected_filter_tags or self._relative_key_matches_tag_filter(entry.relative_key):
            self.render_subfolder_media(entry)

    def choose_root_folder(self) -> None:
        selected = filedialog.askdirectory(title="選擇主資料夾")
        if not selected:
            return
        try:
            self.store.set_root_folder(Path(selected))
        except Exception as exc:
            messagebox.showerror("錯誤", f"無法設定主資料夾：\n{exc}")
            return
        self.root_dir_var.set(str(Path(selected)))
        self.config["root_folder"] = str(Path(selected))
        self._save_config()
        self.refresh_tree()
        self.set_status(f"已設定主資料夾：{selected}")

    def refresh_tree(self, restore_state: Optional[dict] = None) -> None:
        start = self._perf_start()
        self.folder_tree.delete(*self.folder_tree.get_children())
        self.tree_metadata.clear()
        self.path_node_index.clear()
        self._folder_media_filter_cache.clear()
        self.person_entries.clear()
        self.current_entries = []
        self.current_media_items = []
        self.current_view_mode = "entries"
        self.current_subfolder_entry = None
        self.current_scope_path = None
        self.scope_label.configure(text="目前檢視：未選擇")
        self._update_back_buttons_state()

        if self.store.root_folder is None:
            self.set_status("請先選擇主資料夾")
            self.clear_thumbnail_cards()
            return

        root_node = self.folder_tree.insert("", "end", text=self.store.root_folder.name, open=True)
        self.tree_metadata[root_node] = {"type": "root", "path": self.store.root_folder, "lazy_loaded": True}
        self._index_node_path(root_node, self.store.root_folder)

        if self.selected_filter_tags:
            self._build_tag_filtered_tree(root_node)
        else:
            for person_folder in self._get_ordered_people_folders():
                if not self._tree_folder_visible_with_media_filter(person_folder):
                    continue
                person_node = self.folder_tree.insert(root_node, "end", text=person_folder.name, open=False)
                self.tree_metadata[person_node] = {
                    "type": "person",
                    "path": person_folder,
                    "person_name": person_folder.name,
                    "lazy_loaded": True,
                }
                self._index_node_path(person_node, person_folder)
                self._populate_person_tree_shallow(person_node, person_folder)

        self.refresh_filter_panel()
        if restore_state:
            self._restore_tree_state(restore_state)
        self.set_status("已刷新資料夾樹狀清單")
        self._perf_log(
            "refresh_tree",
            start,
            extra=f"people={len(self._get_ordered_people_folders()) if self.store.root_folder else 0}",
        )

    def _populate_person_tree_shallow(self, person_node: str, person_folder: Path) -> None:
        """僅列出第一層子資料夾名稱，不掃描媒體（延遲到選取人物／根節點時再掃描）。"""
        for subfolder in self._get_ordered_subfolders(person_folder):
            if not self._tree_folder_visible_with_media_filter(subfolder):
                continue
            child = self.folder_tree.insert(person_node, "end", text=subfolder.name, open=False)
            self.tree_metadata[child] = {
                "type": "subfolder",
                "entry": None,
                "path": subfolder,
                "person_name": person_folder.name,
                "lazy_loaded": False,
            }
            self._index_node_path(child, subfolder)
            self._ensure_expand_stub(child, subfolder)

    def _relative_key_matches_tag_filter(self, relative_key: str) -> bool:
        if not self.selected_filter_tags:
            return True
        if not relative_key:
            return False
        eff = set(self.tag_repo.get_effective_tags(relative_key))
        return bool(eff.intersection(self.selected_filter_tags))

    def _media_type_filter_enabled(self) -> bool:
        return bool(self.filter_media_video_var.get() or self.filter_media_image_var.get())

    def _folder_matches_media_type_filter(self, folder: Path) -> bool:
        if not self._media_type_filter_enabled():
            return True
        has_image, has_video = self.store.get_folder_media_type_flags(folder)
        want_v = self.filter_media_video_var.get()
        want_i = self.filter_media_image_var.get()
        if want_v and want_i:
            return has_video and has_image
        if want_v:
            return has_video
        if want_i:
            return has_image
        return True

    @staticmethod
    def _duration_filter_enabled(lo_min: Optional[float], hi_min: Optional[float]) -> bool:
        return lo_min is not None or hi_min is not None

    def _media_item_matches_filter(
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
        if not self._duration_filter_enabled(lo_min, hi_min):
            return True
        sec = self.thumbnail_service.get_video_duration_seconds(item.media_path)
        if sec is None:
            return False
        lo_s = (lo_min * 60.0) if lo_min is not None else 0.0
        hi_s = (hi_min * 60.0) if hi_min is not None else float("inf")
        return lo_s <= sec <= hi_s

    def _folder_matches_active_media_filter(
        self,
        folder: Path,
        lo_min: Optional[float],
        hi_min: Optional[float],
        want_video: bool,
        want_image: bool,
    ) -> bool:
        signature = f"v={int(want_video)}|i={int(want_image)}|lo={lo_min}|hi={hi_min}"
        cache_key = (self._path_key(folder), signature)
        cached = self._folder_media_filter_cache.get(cache_key)
        if cached is not None:
            return cached

        items = self.store.list_media_items(folder)
        matched = any(
            self._media_item_matches_filter(item, want_video, want_image, lo_min, hi_min)
            for item in items
        )
        self._folder_media_filter_cache[cache_key] = matched
        return matched

    def _get_duration_bounds_for_tree_filter(self) -> tuple[Optional[float], Optional[float]]:
        try:
            return self._parse_duration_filter_minutes()
        except ValueError:
            # While typing invalid text, do not break tree refresh; "套用" still validates strictly.
            return None, None

    def _tree_folder_visible_with_media_filter(self, folder: Path) -> bool:
        lo_min, hi_min = self._get_duration_bounds_for_tree_filter()
        want_v = self.filter_media_video_var.get()
        want_i = self.filter_media_image_var.get()
        if not want_v and not want_i and not self._duration_filter_enabled(lo_min, hi_min):
            return True
        return self._folder_matches_active_media_filter(folder, lo_min, hi_min, want_v, want_i)

    def _folder_has_visible_subdirs_for_tree(self, folder_path: Path) -> bool:
        lo_min, hi_min = self._get_duration_bounds_for_tree_filter()
        want_v = self.filter_media_video_var.get()
        want_i = self.filter_media_image_var.get()
        if not want_v and not want_i and not self._duration_filter_enabled(lo_min, hi_min):
            return self._folder_has_subdirs(folder_path)
        try:
            for sub in self.store.get_subfolders(folder_path):
                if self._folder_matches_active_media_filter(sub, lo_min, hi_min, want_v, want_i):
                    return True
        except Exception:
            return False
        return False

    def _apply_media_entry_filter(self, entries: list[SubfolderEntry]) -> list[SubfolderEntry]:
        lo_min, hi_min = self._get_duration_bounds_for_tree_filter()
        want_v = self.filter_media_video_var.get()
        want_i = self.filter_media_image_var.get()
        if not want_v and not want_i and not self._duration_filter_enabled(lo_min, hi_min):
            return entries
        return [
            e
            for e in entries
            if self._folder_matches_active_media_filter(e.subfolder_path, lo_min, hi_min, want_v, want_i)
        ]

    def _filter_media_items_by_type_list(
        self, items: list[MediaItem], want_v: bool, want_i: bool
    ) -> list[MediaItem]:
        if not want_v and not want_i:
            return list(items)
        if want_v and want_i:
            return list(items)
        if want_v:
            return [m for m in items if m.media_type == "video"]
        return [m for m in items if m.media_type == "image"]

    def _filter_media_items_for_preview(self, items: list[MediaItem]) -> list[MediaItem]:
        return self._filter_media_items_by_type_list(
            items,
            self.filter_media_video_var.get(),
            self.filter_media_image_var.get(),
        )

    def _parse_duration_filter_minutes(self) -> tuple[Optional[float], Optional[float]]:
        """兩欄皆空白表示不套用影片長度篩選；僅填一側則另一側視為無上限／無下限。"""
        s_lo = self.filter_duration_min_var.get().strip()
        s_hi = self.filter_duration_max_var.get().strip()
        if not s_lo and not s_hi:
            return None, None
        lo: Optional[float] = None
        hi: Optional[float] = None
        if s_lo:
            try:
                lo = float(s_lo)
            except ValueError as exc:
                raise ValueError("「最短」分鐘請填數字（可含小數）。") from exc
            if lo < 0:
                raise ValueError("「最短」分鐘不可為負數。")
        if s_hi:
            try:
                hi = float(s_hi)
            except ValueError as exc:
                raise ValueError("「最長」分鐘請填數字（可含小數）。") from exc
            if hi < 0:
                raise ValueError("「最長」分鐘不可為負數。")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("最短分鐘不可大於最長分鐘。")
        return lo, hi

    def _filter_items_by_duration_minutes(
        self, items: list[MediaItem], lo_min: Optional[float], hi_min: Optional[float]
    ) -> list[MediaItem]:
        if lo_min is None and hi_min is None:
            return list(items)
        lo_s = (lo_min * 60.0) if lo_min is not None else 0.0
        hi_s = (hi_min * 60.0) if hi_min is not None else float("inf")
        out: list[MediaItem] = []
        for m in items:
            if m.media_type == "image":
                out.append(m)
                continue
            sec = self.thumbnail_service.get_video_duration_seconds(m.media_path)
            if sec is None:
                continue
            if lo_s <= sec <= hi_s:
                out.append(m)
        return out

    def _scan_media_for_preview_worker(
        self,
        folder: Path,
        want_video: bool,
        want_image: bool,
        lo_min: Optional[float],
        hi_min: Optional[float],
    ) -> tuple[list[MediaItem], list[MediaItem]]:
        raw = self.store.list_media_items(folder)
        typed = self._filter_media_items_by_type_list(raw, want_video, want_image)
        if lo_min is None and hi_min is None:
            return raw, typed
        return raw, self._filter_items_by_duration_minutes(typed, lo_min, hi_min)

    def on_toggle_filter_tags(self) -> None:
        self.filter_tags_expanded = not self.filter_tags_expanded
        if self.filter_tags_expanded:
            self.filter_tags_container.pack(fill="x", padx=8, pady=(0, 6), after=self.filter_tags_header_frame)
            self.filter_tags_toggle_btn.configure(text="▼ 收合標籤")
        else:
            self.filter_tags_container.pack_forget()
            self.filter_tags_toggle_btn.configure(text="▶ 展開標籤")

    def on_apply_duration_filter(self) -> None:
        try:
            self._parse_duration_filter_minutes()
        except ValueError as exc:
            messagebox.showerror("影片長度篩選", str(exc))
            return
        self._refresh_tree_and_reload_selection()

    def _refresh_tree_and_reload_selection(self) -> None:
        tree_state = self._capture_tree_state()
        self.refresh_tree(restore_state=tree_state)
        selected = self.folder_tree.selection()
        if selected:
            self._apply_tree_selection_from_item_id(selected[0])
        else:
            self.clear_thumbnail_cards()
            self.scope_label.configure(text="目前檢視：未選擇")
            self.current_scope_path = None
            self._update_back_buttons_state()
            self.set_status("就緒")

    def on_media_type_filter_changed(self) -> None:
        self._refresh_tree_and_reload_selection()

    def _collect_tag_filter_state_for_person(
        self,
        person_folder: Path,
        person_name: str,
        lo_min: Optional[float],
        hi_min: Optional[float],
        want_video: bool,
        want_image: bool,
    ) -> tuple[set[str], list[SubfolderEntry]]:
        matching_keys: set[str] = set()
        try:
            for dirpath, dirnames, _ in os.walk(person_folder):
                for d in dirnames:
                    path = Path(dirpath) / d
                    try:
                        rk = self.store.to_relative_key(path)
                    except Exception:
                        continue
                    if self._relative_key_matches_tag_filter(rk):
                        if not self._folder_matches_active_media_filter(path, lo_min, hi_min, want_video, want_image):
                            continue
                        matching_keys.add(rk)
        except Exception:
            return set(), []

        visible: set[str] = set()
        for rk in matching_keys:
            parts = rk.split("/")
            for i in range(len(parts)):
                visible.add("/".join(parts[: i + 1]))

        entries: list[SubfolderEntry] = []
        root = self.store.ensure_root_folder()
        for rk in sorted(matching_keys, key=lambda x: (x.count("/"), x.lower())):
            folder_path = root.joinpath(*rk.split("/"))
            if folder_path.is_dir():
                entries.append(self._build_entry_for_folder(folder_path, person_name))

        return visible, entries

    def _build_tag_filtered_tree(self, root_node: str) -> None:
        lo_min, hi_min = self._get_duration_bounds_for_tree_filter()
        want_v = self.filter_media_video_var.get()
        want_i = self.filter_media_image_var.get()
        for person_folder in self._get_ordered_people_folders():
            if not self._folder_matches_active_media_filter(person_folder, lo_min, hi_min, want_v, want_i):
                continue
            visible, matching_entries = self._collect_tag_filter_state_for_person(
                person_folder,
                person_folder.name,
                lo_min,
                hi_min,
                want_v,
                want_i,
            )
            if not visible:
                continue
            person_node = self.folder_tree.insert(root_node, "end", text=person_folder.name, open=True)
            self.tree_metadata[person_node] = {
                "type": "person",
                "path": person_folder,
                "person_name": person_folder.name,
                "lazy_loaded": True,
            }
            self._index_node_path(person_node, person_folder)
            self.person_entries[person_folder.name] = matching_entries
            self._populate_filtered_subtree(person_node, person_folder.name, visible)

    def _populate_filtered_subtree(self, person_node: str, person_name: str, visible_keys: set[str]) -> None:
        prefix = person_name + "/"
        subtree_keys = {k for k in visible_keys if k.startswith(prefix) or k == person_name}
        depth_keys = sorted(subtree_keys, key=lambda k: (k.count("/"), k.lower()))
        key_to_node: dict[str, str] = {person_name: person_node}
        root = self.store.ensure_root_folder()

        for rk in depth_keys:
            if rk == person_name:
                continue
            parts = rk.split("/")
            if not parts or parts[0] != person_name:
                continue
            parent_key = "/".join(parts[:-1])
            parent_id = key_to_node.get(parent_key)
            if parent_id is None:
                continue
            folder_path = root.joinpath(*parts)
            if not folder_path.is_dir():
                continue
            entry = self._build_entry_for_folder(folder_path, person_name)
            child = self.folder_tree.insert(parent_id, "end", text=entry.subfolder_name, open=False)
            self.tree_metadata[child] = {
                "type": "subfolder",
                "entry": entry,
                "path": folder_path,
                "person_name": person_name,
                "lazy_loaded": True,
            }
            self._index_node_path(child, folder_path)
            key_to_node[rk] = child
            has_visible_child = any(k != rk and k.startswith(rk + "/") for k in subtree_keys)
            if has_visible_child:
                self.folder_tree.item(child, open=True)

    def _ensure_expand_stub(self, node_id: str, folder_path: Path) -> None:
        if self._folder_has_visible_subdirs_for_tree(folder_path):
            stub = self.folder_tree.insert(node_id, "end", text="...")
            self.tree_metadata[stub] = {"type": "stub"}

    def _folder_has_subdirs(self, folder_path: Path) -> bool:
        try:
            return any(p.is_dir() for p in folder_path.iterdir())
        except Exception:
            return False

    def on_tree_open(self, _event=None) -> None:
        node_id = self.folder_tree.focus()
        self._expand_node(node_id)

    def _expand_node(self, node_id: str) -> None:
        if self.selected_filter_tags:
            return
        payload = self.tree_metadata.get(node_id) or {}
        if payload.get("type") not in {"person", "subfolder"} or payload.get("lazy_loaded"):
            return
        start = self._perf_start()

        for child in self.folder_tree.get_children(node_id):
            if (self.tree_metadata.get(child) or {}).get("type") == "stub":
                self.folder_tree.delete(child)
                self.tree_metadata.pop(child, None)

        parent_path = Path(payload["path"])
        person_name = payload["person_name"]
        subfolders = self._get_ordered_subfolders(parent_path)
        for subfolder in subfolders:
            if not self._tree_folder_visible_with_media_filter(subfolder):
                continue
            child = self.folder_tree.insert(node_id, "end", text=subfolder.name, open=False)
            self.tree_metadata[child] = {
                "type": "subfolder",
                "entry": None,
                "path": subfolder,
                "person_name": person_name,
                "lazy_loaded": False,
            }
            self._index_node_path(child, subfolder)
            self._ensure_expand_stub(child, subfolder)
        payload["lazy_loaded"] = True
        self.folder_tree.item(node_id, open=True)
        self._perf_log("tree_open_load_children", start, extra=f"count={len(subfolders)}")

    def _path_key(self, path_obj: Path) -> str:
        try:
            return str(Path(path_obj).resolve())
        except Exception:
            return str(path_obj)

    def _index_node_path(self, node_id: str, path_obj: Path) -> None:
        self.path_node_index[self._path_key(path_obj)] = node_id

    def _capture_tree_state(self) -> dict:
        expanded_paths: list[str] = []
        for node_id, payload in self.tree_metadata.items():
            path_obj = payload.get("path")
            if not path_obj:
                continue
            try:
                if self.folder_tree.item(node_id, "open"):
                    expanded_paths.append(self._path_key(path_obj))
            except Exception:
                continue

        selected_path = None
        selected = self.folder_tree.selection()
        if selected:
            payload = self.tree_metadata.get(selected[0]) or {}
            path_obj = payload.get("path")
            if path_obj:
                selected_path = self._path_key(path_obj)

        y_pos = 0.0
        try:
            y_pos = float(self.folder_tree.yview()[0])
        except Exception:
            pass

        return {
            "expanded_paths": expanded_paths,
            "selected_path": selected_path,
            "y_pos": y_pos,
        }

    def _restore_tree_state(self, state: dict) -> None:
        expanded_paths = state.get("expanded_paths") or []
        expanded_paths = sorted(expanded_paths, key=lambda p: p.count("\\") + p.count("/"))
        for path_key in expanded_paths:
            node_id = self.path_node_index.get(path_key)
            if not node_id:
                continue
            self.folder_tree.item(node_id, open=True)
            self._expand_node(node_id)

        selected_path = state.get("selected_path")
        if selected_path:
            node_id = self.path_node_index.get(selected_path)
            if node_id:
                self.folder_tree.selection_set(node_id)
                self.folder_tree.focus(node_id)
                self.folder_tree.see(node_id)

        y_pos = state.get("y_pos")
        if isinstance(y_pos, (int, float)):
            self.root.after(0, lambda: self.folder_tree.yview_moveto(float(y_pos)))

    def _ensure_tree_child_order_dict(self) -> dict:
        raw = self.config.get("tree_child_order")
        if not isinstance(raw, dict):
            raw = {}
            self.config["tree_child_order"] = raw
        return raw

    def _apply_saved_child_order(self, parent_path: Path, children: list[Path]) -> list[Path]:
        if not children:
            return []
        order_map = self._ensure_tree_child_order_dict()
        key = self._path_key(parent_path)
        preferred = order_map.get(key)
        if not preferred or not isinstance(preferred, list):
            return sorted(children, key=lambda p: p.name.lower())
        name_to_path = {p.name: p for p in children}
        ordered: list[Path] = []
        seen: set[str] = set()
        for name in preferred:
            if not isinstance(name, str):
                continue
            p = name_to_path.get(name)
            if p is not None and name not in seen:
                ordered.append(p)
                seen.add(name)
        for p in sorted(children, key=lambda x: x.name.lower()):
            if p.name not in seen:
                ordered.append(p)
        return ordered

    def _get_ordered_people_folders(self) -> list[Path]:
        root = self.store.ensure_root_folder()
        raw = [p for p in root.iterdir() if p.is_dir()]
        return self._apply_saved_child_order(root, raw)

    def _get_ordered_subfolders(self, folder: Path) -> list[Path]:
        parent = Path(folder)
        raw = [p for p in parent.iterdir() if p.is_dir()]
        return self._apply_saved_child_order(parent, raw)

    def _order_entries_by_saved_tree(self, parent_path: Path, entries: list[SubfolderEntry]) -> list[SubfolderEntry]:
        if not entries:
            return []
        paths = [Path(e.subfolder_path) for e in entries]
        ordered_paths = self._apply_saved_child_order(Path(parent_path), paths)
        by_res = {Path(e.subfolder_path).resolve(): e for e in entries}
        out: list[SubfolderEntry] = []
        for p in ordered_paths:
            e = by_res.get(Path(p).resolve())
            if e is not None:
                out.append(e)
        return out

    def _persist_child_order_from_tree_parent(self, parent_node_id: str) -> None:
        meta = self.tree_metadata.get(parent_node_id) or {}
        path_obj = meta.get("path")
        if path_obj is None:
            return
        names: list[str] = []
        for cid in self.folder_tree.get_children(parent_node_id):
            cm = self.tree_metadata.get(cid) or {}
            if cm.get("type") not in {"person", "subfolder"}:
                continue
            cp = cm.get("path")
            if cp is not None:
                names.append(Path(cp).name)
        key = self._path_key(Path(path_obj))
        self._ensure_tree_child_order_dict()[key] = names
        self._save_config()

    def _remove_name_from_tree_order(self, parent_path: Path, name: str) -> None:
        key = self._path_key(parent_path)
        order_map = self._ensure_tree_child_order_dict()
        cur = order_map.get(key)
        if not isinstance(cur, list) or name not in cur:
            return
        order_map[key] = [x for x in cur if x != name]
        self._save_config()

    def _append_name_to_tree_order(self, parent_path: Path, name: str) -> None:
        key = self._path_key(parent_path)
        order_map = self._ensure_tree_child_order_dict()
        cur = list(order_map.get(key)) if isinstance(order_map.get(key), list) else []
        cur = [x for x in cur if x != name]
        cur.append(name)
        order_map[key] = cur
        self._save_config()

    def _prepend_name_to_tree_order(self, parent_path: Path, name: str) -> None:
        key = self._path_key(parent_path)
        order_map = self._ensure_tree_child_order_dict()
        cur = list(order_map.get(key)) if isinstance(order_map.get(key), list) else []
        cur = [x for x in cur if x != name]
        cur.insert(0, name)
        order_map[key] = cur
        self._save_config()

    def _tree_state_expand_to_folder(self, folder: Path, base: Optional[dict] = None) -> dict:
        state = dict(base) if base is not None else {}
        ex = list(state.get("expanded_paths") or [])
        ex_set = set(ex)
        folder_r = Path(folder).resolve()
        root_r = Path(self.store.root_folder).resolve() if self.store.root_folder else None
        if root_r is not None:
            cur = folder_r.parent
            for _ in range(512):
                try:
                    cur.resolve().relative_to(root_r)
                except ValueError:
                    break
                k = self._path_key(cur)
                if k not in ex_set:
                    ex.append(k)
                    ex_set.add(k)
                if cur == root_r:
                    break
                nxt = cur.parent
                if nxt == cur:
                    break
                cur = nxt
        state["expanded_paths"] = sorted(ex, key=lambda p: p.count("\\") + p.count("/"))
        state["selected_path"] = self._path_key(folder_r)
        return state

    def _refresh_tree_after_new_folder_transfer(self, parent_path: Path, new_folder: Path) -> None:
        self.store.invalidate_folder_cache(parent_path)
        self.store.invalidate_folder_cache(new_folder)
        self._prepend_name_to_tree_order(parent_path, new_folder.name)
        snap = self._capture_tree_state()
        self.refresh_tree(restore_state=self._tree_state_expand_to_folder(new_folder.resolve(), snap))

    def _tree_order_after_delete_folder(self, deleted_folder: Path) -> None:
        parent = deleted_folder.parent
        self._remove_name_from_tree_order(parent, deleted_folder.name)
        order_map = self._ensure_tree_child_order_dict()
        dk = self._path_key(deleted_folder)
        if dk in order_map:
            del order_map[dk]
        self._save_config()

    def _prune_tree_state_after_deleted_paths(self, state: dict, deleted: list[Path]) -> dict:
        if not deleted:
            return state
        roots = [Path(d).resolve() for d in deleted]

        def touched_by_delete(p: Path) -> bool:
            pr = p.resolve()
            for r in roots:
                try:
                    pr.relative_to(r)
                    return True
                except ValueError:
                    if pr == r:
                        return True
            return False

        out = dict(state)
        ex_new: list[str] = []
        for x in out.get("expanded_paths") or []:
            if not isinstance(x, str):
                continue
            try:
                px = Path(x).resolve()
            except Exception:
                continue
            if not touched_by_delete(px):
                ex_new.append(self._path_key(px))
        out["expanded_paths"] = ex_new

        sp = out.get("selected_path")
        if isinstance(sp, str):
            try:
                ps = Path(sp).resolve()
                if touched_by_delete(ps):
                    fallback = roots[0].parent.resolve()
                    if self.store.root_folder:
                        root_r = Path(self.store.root_folder).resolve()
                        try:
                            fallback.relative_to(root_r)
                        except ValueError:
                            fallback = root_r
                    out["selected_path"] = self._path_key(fallback)
            except Exception:
                pass
        return out

    def _rewrite_tree_order_after_rename(self, old_path: Path, new_path: Path) -> None:
        order_map = self._ensure_tree_child_order_dict()
        try:
            old_r = Path(old_path).resolve()
            new_r = Path(new_path).resolve()
        except Exception:
            self._save_config()
            return
        old_pk = self._path_key(old_r)
        new_pk = self._path_key(new_r)
        if old_pk in order_map:
            order_map[new_pk] = order_map.pop(old_pk)
        parent_key = self._path_key(old_r.parent)
        lst = order_map.get(parent_key)
        if isinstance(lst, list) and old_r.name in lst:
            order_map[parent_key] = [new_r.name if x == old_r.name else x for x in lst]
        for k in list(order_map.keys()):
            try:
                kp = Path(k).resolve()
                rel = kp.relative_to(old_r)
            except (ValueError, OSError):
                continue
            nk = self._path_key(new_r / rel)
            if nk != k:
                order_map[nk] = order_map.pop(k)
        self._save_config()

    def _hide_tree_drop_visual(self) -> None:
        if self._tree_drop_line is not None:
            try:
                self._tree_drop_line.place_forget()
            except tk.TclError:
                pass
        if self._tree_drop_child_frame is not None:
            try:
                self._tree_drop_child_frame.place_forget()
            except tk.TclError:
                pass

    def _ensure_tree_drop_line(self) -> tk.Frame:
        if self._tree_host is None:
            raise RuntimeError("tree host missing")
        if self._tree_drop_line is None or not self._tree_drop_line.winfo_exists():
            self._tree_drop_line = tk.Frame(self._tree_host, bg="#2ea3ff", height=3, bd=0, highlightthickness=0)
        return self._tree_drop_line

    def _ensure_tree_drop_child_frame(self) -> tk.Frame:
        if self._tree_host is None:
            raise RuntimeError("tree host missing")
        if self._tree_drop_child_frame is None or not self._tree_drop_child_frame.winfo_exists():
            self._tree_drop_child_frame = tk.Frame(self._tree_host, bg="#144870", bd=0, highlightthickness=0)
        else:
            try:
                self._tree_drop_child_frame.configure(bg="#144870")
            except tk.TclError:
                pass
        return self._tree_drop_child_frame

    def _show_tree_drop_insert_line(self, item_id: str, before: bool) -> None:
        if self._tree_host is None:
            return
        bbox = self.folder_tree.bbox(item_id)
        if not bbox:
            self._hide_tree_drop_visual()
            return
        _bx, by, _bw, bh = bbox
        y_line = max(0, by - 2) if before else by + bh + 1
        self.folder_tree.update_idletasks()
        ox = self.folder_tree.winfo_x()
        oy = self.folder_tree.winfo_y()
        bx, _by, _bw2, _bh2 = bbox
        left = ox + max(bx - 2, 0)
        w = max(self.folder_tree.winfo_width() - (left - ox), 24)
        if self._tree_drop_child_frame is not None:
            try:
                self._tree_drop_child_frame.place_forget()
            except tk.TclError:
                pass
        line = self._ensure_tree_drop_line()
        line.place(in_=self._tree_host, x=left, y=oy + y_line, width=w, height=3)

    def _show_tree_drop_as_child_highlight(self, item_id: str) -> None:
        if self._tree_host is None:
            return
        bbox = self.folder_tree.bbox(item_id)
        if not bbox:
            self._hide_tree_drop_visual()
            return
        bx, by, bw, bh = bbox
        self.folder_tree.update_idletasks()
        ox = self.folder_tree.winfo_x()
        oy = self.folder_tree.winfo_y()
        left = ox + max(bx - 2, 0)
        w = max(self.folder_tree.winfo_width() - (left - ox), 24)
        if self._tree_drop_line is not None:
            try:
                self._tree_drop_line.place_forget()
            except tk.TclError:
                pass
        panel = self._ensure_tree_drop_child_frame()
        panel.place(in_=self._tree_host, x=left, y=oy + by, width=w, height=max(bh, 18))

    def _tree_same_parent_vertical_zone(self, y_local: float, row: str) -> str:
        """同層拖曳時依游標判定：列前插入 before、移入列內 into、列後插入 after。"""
        bbox = self.folder_tree.bbox(row)
        if not bbox:
            return "after"
        _bx, by, _bw, bh = bbox
        if bh <= 0:
            return "after"
        rel_y = (float(y_local) - float(by)) / float(bh)
        if rel_y < 0.28:
            return "before"
        if rel_y > 0.72:
            return "after"
        return "into"

    def _tree_drop_intent(self, src: str, row: str, y_local: float) -> tuple[Optional[str], Optional[str], Optional[int]]:
        """
        回傳拖放意圖：
        - action: "into"（成為 row 子項）或 "insert"（插到 row 同層前/後）
        - target_parent: 目標父節點（Tree item id）
        - insert_index: action 為 insert 時使用
        """
        if not src or not row or src == row:
            return None, None, None
        src_meta = self.tree_metadata.get(src) or {}
        dst_meta = self.tree_metadata.get(row) or {}
        if src_meta.get("type") not in {"person", "subfolder"}:
            return None, None, None
        if dst_meta.get("type") not in {"root", "person", "subfolder"}:
            return None, None, None
        if dst_meta.get("type") == "stub":
            return None, None, None

        zone = self._tree_same_parent_vertical_zone(y_local, row)
        if dst_meta.get("type") == "root":
            return None, None, None
        if zone == "into":
            return "into", row, None

        target_parent = self.folder_tree.parent(row)
        if not target_parent and src:
            target_parent = self.folder_tree.parent(src)
        siblings = [
            cid
            for cid in self.folder_tree.get_children(target_parent)
            if (self.tree_metadata.get(cid) or {}).get("type") in {"person", "subfolder"}
        ]
        if src in siblings:
            siblings = [x for x in siblings if x != src]
        try:
            idx = siblings.index(row)
        except ValueError:
            return None, None, None
        insert_index = idx if zone == "before" else idx + 1
        return "insert", target_parent, insert_index

    def _insert_name_to_tree_order(self, parent_path: Path, name: str, index: int) -> None:
        key = self._path_key(parent_path)
        order_map = self._ensure_tree_child_order_dict()
        cur = list(order_map.get(key)) if isinstance(order_map.get(key), list) else []
        cur = [x for x in cur if x != name]
        safe_idx = max(0, min(int(index), len(cur)))
        cur.insert(safe_idx, name)
        order_map[key] = cur
        self._save_config()

    def _try_tree_move_folder_to_parent(
        self,
        src: str,
        target_parent_row: str,
        insert_index: Optional[int] = None,
    ) -> bool:
        """
        將 src 對應資料夾移到 target_parent_row 之下。
        insert_index 為 None 時代表附加到尾端；否則插入指定順序索引。
        """
        src_meta = self.tree_metadata.get(src) or {}
        parent_meta = self.tree_metadata.get(target_parent_row) or {}
        if src_meta.get("type") not in {"person", "subfolder"}:
            return False
        if parent_meta.get("type") not in {"root", "person", "subfolder"}:
            return False
        src_path = Path(src_meta["path"]).resolve()
        if parent_meta.get("type") == "root":
            if self.store.root_folder is None:
                return False
            target_parent_path = Path(self.store.root_folder).resolve()
            parent_label = target_parent_path.name
        else:
            target_parent_path = Path(parent_meta["path"]).resolve()
            parent_label = target_parent_path.name
        if not src_path.is_dir() or not target_parent_path.is_dir():
            return False

        if src_path.parent == target_parent_path and insert_index is not None:
            return False
        if src_path.parent == target_parent_path and insert_index is None:
            return False

        try:
            if target_parent_path == src_path or target_parent_path.is_relative_to(src_path):
                messagebox.showerror("錯誤", "目標不可位於被拖曳的資料夾內部。")
                return False
        except (ValueError, OSError):
            messagebox.showerror("錯誤", "無法驗證搬移路徑。")
            return False

        dest_dir = self._build_non_conflict_dest_dir(target_parent_path, src_path.name)
        action_desc = "移入" if insert_index is None else "插入"
        if not messagebox.askyesno(
            "確認搬移資料夾",
            f"確定將「{src_path.name}」{action_desc}到「{parent_label}」底下？\n"
            f"新位置：{dest_dir}\n\n（標籤鍵將盡力同步；實體檔案會一併搬移）",
        ):
            return False

        old_parent = src_path.parent
        try:
            shutil.move(str(src_path), str(dest_dir))
        except OSError as exc:
            messagebox.showerror("搬移失敗", str(exc))
            return False

        self._migrate_tags_after_folder_move(src_path, dest_dir)
        self.store.clear_cache()
        self._remove_name_from_tree_order(old_parent, src_path.name)
        if insert_index is None:
            self._append_name_to_tree_order(target_parent_path, dest_dir.name)
        else:
            self._insert_name_to_tree_order(target_parent_path, dest_dir.name, insert_index)

        tree_state = self._capture_tree_state()
        old_r = src_path.resolve()
        new_r = dest_dir.resolve()
        new_sel = self._path_key(new_r)

        def _rewrite_moved_path_str(ps: str) -> str:
            try:
                pr = Path(ps).resolve()
            except Exception:
                return ps
            if pr == old_r:
                return new_sel
            try:
                rel = pr.relative_to(old_r)
                return self._path_key(new_r / rel)
            except ValueError:
                return ps

        sp = tree_state.get("selected_path")
        if isinstance(sp, str):
            tree_state["selected_path"] = _rewrite_moved_path_str(sp)
        ex_in = tree_state.get("expanded_paths") or []
        tree_state["expanded_paths"] = [_rewrite_moved_path_str(x) for x in ex_in if isinstance(x, str)]

        self.refresh_tree(restore_state=tree_state)
        self.set_status(f"已搬移資料夾至：{dest_dir}")
        return True

    def _try_tree_reparent_folder_drop(self, src: str, dst_row: str) -> bool:
        """將樹節點 src 對應的資料夾移入 dst_row 底下；成功回傳 True。"""
        return self._try_tree_move_folder_to_parent(src, dst_row, insert_index=None)

    def _on_tree_drag_press(self, event: tk.Event) -> None:
        self._tree_drag_source = None
        self._tree_drag_start_xy = None
        if self.selected_filter_tags:
            return
        row = self.folder_tree.identify_row(event.y)
        if not row:
            return
        meta = self.tree_metadata.get(row) or {}
        if meta.get("type") in (None, "stub", "root"):
            return
        self._tree_drag_source = row
        self._tree_drag_start_xy = (event.x, event.y)

    def _on_tree_drag_motion(self, event: tk.Event) -> None:
        src = self._tree_drag_source
        if not src or self.selected_filter_tags:
            return
        if self._tree_drag_start_xy is None:
            return
        dx = abs(event.x - self._tree_drag_start_xy[0])
        dy = abs(event.y - self._tree_drag_start_xy[1])
        if dx + dy < 9:
            self._hide_tree_drop_visual()
            return
        self._tree_drag_visual_active = True
        self._show_drag_hint("上緣/下緣：插入到該層級；列中間：移入該資料夾", event.x_root, event.y_root)
        self._move_drag_hint(event.x_root, event.y_root)

        row = self.folder_tree.identify_row(event.y)
        if not row or row == src:
            self._hide_tree_drop_visual()
            return
        dst_meta = self.tree_metadata.get(row) or {}
        if dst_meta.get("type") == "stub":
            self._hide_tree_drop_visual()
            return

        action, _target_parent, insert_index = self._tree_drop_intent(src, row, float(event.y))
        if action == "into":
            self._show_tree_drop_as_child_highlight(row)
            return
        if action == "insert":
            self._show_tree_drop_insert_line(row, before=(insert_index is not None and insert_index >= 0 and self._tree_same_parent_vertical_zone(float(event.y), row) == "before"))
            return
        self._hide_tree_drop_visual()

    def _on_root_button1_release_tree_drag(self, event: tk.Event) -> None:
        tree_dragging = self._tree_drag_source is not None or self._tree_drag_visual_active
        self._hide_tree_drop_visual()
        if tree_dragging:
            self._hide_drag_hint()
        self._tree_drag_visual_active = False
        src = self._tree_drag_source
        self._tree_drag_source = None
        self._tree_drag_start_xy = None
        if not src or self.selected_filter_tags:
            return
        try:
            px = self.root.winfo_pointerx()
            py_scr = self.root.winfo_pointery()
            trx = self.folder_tree.winfo_rootx()
            tree_y = self.folder_tree.winfo_rooty()
            tw = self.folder_tree.winfo_width()
            th = self.folder_tree.winfo_height()
        except tk.TclError:
            return
        if not (trx <= px < trx + max(tw, 1) and tree_y <= py_scr < tree_y + max(th, 1)):
            return
        y_local = py_scr - tree_y
        row = self.folder_tree.identify_row(y_local)
        if not row or row == src:
            return
        src_meta = self.tree_metadata.get(src) or {}
        dst_meta = self.tree_metadata.get(row) or {}
        if src_meta.get("type") not in {"person", "subfolder"}:
            return
        if dst_meta.get("type") not in {"person", "subfolder", "root"}:
            return
        if dst_meta.get("type") == "stub":
            return

        action, target_parent, insert_index = self._tree_drop_intent(src, row, y_local)
        if action == "into":
            self._try_tree_reparent_folder_drop(src, row)
            return
        if action != "insert" or target_parent is None or insert_index is None:
            return
        src_parent = self.folder_tree.parent(src)
        if src_parent == target_parent:
            siblings = [
                cid
                for cid in self.folder_tree.get_children(src_parent)
                if (self.tree_metadata.get(cid) or {}).get("type") in {"person", "subfolder"}
            ]
            if src not in siblings:
                return
            siblings_wo = [x for x in siblings if x != src]
            pos = max(0, min(int(insert_index), len(siblings_wo)))
            self.folder_tree.move(src, src_parent, pos)
            self._persist_child_order_from_tree_parent(src_parent)
            self.set_status("已更新樹狀排序（已儲存）")
            return
        self._try_tree_move_folder_to_parent(src, target_parent, insert_index=insert_index)

    def _migrate_tags_after_folder_move(self, old_path: Path, new_path: Path) -> None:
        try:
            old_rel = self.store.to_relative_key(old_path)
        except Exception:
            old_rel = ""
        if not old_rel:
            return
        try:
            new_rel = self.store.to_relative_key(new_path)
            self.tag_repo.rename_relative_path_root(old_rel, new_rel)
        except Exception:
            self.tag_repo.remove_keys_by_prefix(old_rel)

    @staticmethod
    def _build_non_conflict_dest_dir(parent: Path, base_name: str) -> Path:
        candidate = parent / base_name
        if not candidate.exists():
            return candidate
        index = 1
        while True:
            next_name = f"{base_name}_moved_{index}"
            cand = parent / next_name
            if not cand.exists():
                return cand
            index += 1

    def _confirm_deletion_with_checkbox(self, title: str, message: str) -> bool:
        result = {"ok": False}
        top = tk.Toplevel(self.root)
        top.title(title)
        top.transient(self.root)
        top.grab_set()
        frm = tk.Frame(top, padx=14, pady=12)
        frm.pack(fill="both", expand=True)
        tk.Label(frm, text=message, justify="left", wraplength=420).pack(anchor="w")
        var = tk.BooleanVar(value=False)

        def sync_ok() -> None:
            btn_ok.config(state="normal" if var.get() else "disabled")

        tk.Checkbutton(
            frm,
            text="我確認要永久刪除，且了解此操作無法復原",
            variable=var,
            command=sync_ok,
        ).pack(anchor="w", pady=(10, 6))
        btn_row = tk.Frame(frm)
        btn_row.pack(fill="x", pady=(8, 0))
        def _do_delete() -> None:
            result["ok"] = True
            top.destroy()

        btn_ok = tk.Button(btn_row, text="刪除", state="disabled", command=_do_delete)
        btn_ok.pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="取消", command=top.destroy).pack(side="right")
        top.wait_window(top)
        return bool(result["ok"])

    def _parent_one_level_up_clamped_to_root(self, folder: Path) -> Path:
        """取得資料夾的上一層；若會超出主資料夾根目錄則改為根目錄本身。"""
        try:
            p = Path(folder).expanduser().resolve()
        except OSError:
            p = Path(folder).expanduser()
        if self.store.root_folder is None:
            return p.parent
        root_r = Path(self.store.root_folder).resolve()
        if p == root_r:
            return root_r
        par = p.parent
        try:
            par.relative_to(root_r)
            return par
        except ValueError:
            return root_r

    def _suggested_parent_path_for_new_folder_transfer(self, primary: Path) -> Path:
        try:
            p = Path(primary).expanduser().resolve()
        except OSError:
            p = Path(primary).expanduser()
        if p.is_dir():
            return p
        if self.current_scope_path is not None:
            try:
                sp = Path(self.current_scope_path).expanduser().resolve()
            except OSError:
                sp = Path(self.current_scope_path).expanduser()
            if sp.is_dir():
                return sp
        if self.store.root_folder is not None:
            try:
                rp = Path(self.store.root_folder).expanduser().resolve()
            except OSError:
                rp = Path(self.store.root_folder).expanduser()
            if rp.is_dir():
                return rp
        return p if p.is_dir() else Path(".").resolve()

    def _ask_parent_folder_for_new_transfer(self, suggested: Path) -> Optional[Path]:
        """以可編輯欄位預填父資料夾路徑（Windows 內建選擇器常不顯示 initialdir 文字）。"""
        suggested = self._suggested_parent_path_for_new_folder_transfer(suggested)
        result: dict[str, Optional[Path]] = {"path": None}
        top = tk.Toplevel(self.root)
        top.title("新資料夾要建立在哪裡")
        top.transient(self.root)
        top.grab_set()
        top.configure(bg=self.ui_colors["bg"])
        frm = tk.Frame(top, padx=14, pady=12, bg=self.ui_colors["bg"])
        frm.pack(fill="both", expand=True)
        tk.Label(
            frm,
            text="父層資料夾（預設為「轉移來源所在層」的再上一層，可修改或按「瀏覽…」）：",
            anchor="w",
            bg=self.ui_colors["bg"],
            fg=self.ui_colors["text"],
            wraplength=420,
            justify="left",
            font=(self._platform_font_family(), 11),
        ).pack(fill="x")
        var = tk.StringVar(value=str(suggested))
        ent = tk.Entry(
            frm,
            textvariable=var,
            width=72,
            bg=self.ui_colors["panel"],
            fg=self.ui_colors["text"],
            insertbackground=self.ui_colors["text"],
            selectbackground=self.ui_colors["accent_soft"],
            selectforeground=self.ui_colors["text"],
            highlightthickness=1,
            highlightbackground=self.ui_colors["border"],
            highlightcolor=self.ui_colors["accent"],
            font=(self._platform_font_family(), 11),
        )
        ent.pack(fill="x", pady=(8, 10))

        def browse() -> None:
            cur = var.get().strip()
            init = str(suggested)
            if cur:
                try:
                    cp = Path(cur).expanduser().resolve()
                    if cp.is_dir():
                        init = str(cp)
                except OSError:
                    pass
            picked = filedialog.askdirectory(title="選擇父層資料夾", initialdir=init)
            if picked:
                var.set(picked)

        def ok() -> None:
            raw = var.get().strip()
            if not raw:
                messagebox.showwarning("提示", "請輸入或選擇父層資料夾路徑。", parent=top)
                return
            try:
                p = Path(raw).expanduser().resolve()
            except OSError as exc:
                messagebox.showerror("錯誤", f"路徑無效：\n{exc}", parent=top)
                return
            if not p.is_dir():
                messagebox.showerror("錯誤", f"路徑不存在或不是資料夾：\n{p}", parent=top)
                return
            result["path"] = p
            top.destroy()

        bf = tk.Frame(frm, bg=self.ui_colors["bg"])
        bf.pack(fill="x")
        tk.Button(bf, text="瀏覽…", command=browse).pack(side="left", padx=(0, 8))
        tk.Button(bf, text="確定", command=ok, width=10).pack(side="right", padx=(4, 0))
        tk.Button(bf, text="取消", command=top.destroy, width=10).pack(side="right")

        def _focus_entry() -> None:
            try:
                ent.focus_set()
                ent.selection_range(0, tk.END)
                ent.icursor(tk.END)
            except tk.TclError:
                pass

        top.after(80, _focus_entry)
        top.wait_window(top)
        return result["path"]

    def transfer_selected_to_new_folder(self) -> None:
        if self.current_view_mode == "media":
            selected = [m for m in self.current_media_items if self._item_key_for_media(m) in self.selected_media_paths]
            if not selected and self._context_media_item is not None:
                selected = [self._context_media_item]
            if not selected:
                messagebox.showinfo("提示", "請先在預覽區選取至少一個檔案。")
                return
            if self.current_subfolder_entry is not None:
                base = Path(self.current_subfolder_entry.subfolder_path).resolve()
            else:
                base = Path(selected[0].media_path).resolve().parent
            suggested_parent = self._parent_one_level_up_clamped_to_root(base)
        else:
            selected_entries = [e for e in self.current_entries if self._item_key_for_entry(e) in self.selected_entry_keys]
            if not selected_entries and self._context_target is not None and self.current_view_mode == "entries":
                selected_entries = [self._context_target]
            if not selected_entries:
                messagebox.showinfo("提示", "請先在預覽區選取至少一個資料夾。")
                return
            base = Path(selected_entries[0].subfolder_path).resolve().parent
            suggested_parent = self._parent_one_level_up_clamped_to_root(base)

        parent_path = self._ask_parent_folder_for_new_transfer(suggested_parent)
        if parent_path is None:
            return

        new_name = simpledialog.askstring(
            "新資料夾名稱",
            f"將在「{parent_path.name}」底下建立資料夾，並移入已選項目：",
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not self._is_valid_folder_basename(new_name):
            messagebox.showwarning("警告", "名稱無效：不可為空，且不可包含 \\ / : * ? \" < > | 等字元。")
            return

        new_folder = parent_path / new_name
        if new_folder.exists():
            messagebox.showerror("錯誤", f"已存在同名項目：{new_name}")
            return

        try:
            new_folder.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            messagebox.showerror("建立失敗", str(exc))
            return

        if self.current_view_mode == "media":
            if not messagebox.askyesno(
                "確認轉移",
                f"確定將 {len(selected)} 個檔案移動到新資料夾「{new_name}」？",
            ):
                try:
                    new_folder.rmdir()
                except OSError:
                    pass
                return
            moved_count = 0
            renamed_count = 0
            failed_count = 0
            touched_parents: set[Path] = set()
            for item in selected:
                src = Path(item.media_path).resolve()
                if not src.is_file():
                    failed_count += 1
                    continue
                dst = new_folder / src.name
                if dst.exists():
                    dst = self._build_non_conflict_file_path(new_folder, src.name)
                    renamed_count += 1
                try:
                    shutil.move(str(src), str(dst))
                    moved_count += 1
                    touched_parents.add(src.parent)
                except OSError:
                    failed_count += 1
            for p in touched_parents:
                self.store.invalidate_folder_cache(p)
            cur = self.current_subfolder_entry
            if cur is not None and self.current_view_mode == "media":
                self.render_subfolder_media(cur)
            self._refresh_tree_after_new_folder_transfer(parent_path, new_folder)
            self.set_status(
                f"已建立「{new_name}」並移入檔案：成功 {moved_count}，改名 {renamed_count}，失敗 {failed_count}"
            )
            return

        selected_entries = [e for e in self.current_entries if self._item_key_for_entry(e) in self.selected_entry_keys]
        if not selected_entries and self._context_target is not None:
            selected_entries = [self._context_target]
        if not messagebox.askyesno(
            "確認轉移",
            f"確定將 {len(selected_entries)} 個資料夾移入新資料夾「{new_name}」？\n"
            "（整個資料夾會搬移到該路徑下；若同名已存在將自動改名）",
        ):
            try:
                new_folder.rmdir()
            except OSError:
                pass
            return

        moved_ok = 0
        failed_count = 0
        for entry in selected_entries:
            src = Path(entry.subfolder_path).resolve()
            if not src.is_dir():
                failed_count += 1
                continue
            if new_folder.resolve() == src.resolve() or new_folder.resolve().is_relative_to(src.resolve()):
                failed_count += 1
                continue
            dest = self._build_non_conflict_dest_dir(new_folder, src.name)
            try:
                shutil.move(str(src), str(dest))
            except OSError:
                failed_count += 1
                continue
            self._migrate_tags_after_folder_move(src, dest)
            self._tree_order_after_delete_folder(src)
            self._append_name_to_tree_order(new_folder, dest.name)
            moved_ok += 1

        self.store.clear_cache()
        self._refresh_tree_after_new_folder_transfer(parent_path, new_folder)
        self.set_status(f"已建立「{new_name}」並移入資料夾：成功 {moved_ok}，失敗 {failed_count}")

    def delete_selected_preview_items(self) -> None:
        if self.current_view_mode == "media":
            selected = [m for m in self.current_media_items if self._item_key_for_media(m) in self.selected_media_paths]
            if not selected and self._context_media_item is not None:
                selected = [self._context_media_item]
            if not selected:
                messagebox.showinfo("提示", "請先選取要刪除的檔案。")
                return
            names = "\n".join(Path(m.media_path).name for m in selected[:12])
            extra = f"\n… 等共 {len(selected)} 個檔案" if len(selected) > 12 else ""
            msg = f"即將永久刪除以下檔案：\n\n{names}{extra}"
            if not self._confirm_deletion_with_checkbox("刪除檔案", msg):
                return
            deleted = 0
            failed = 0
            parents: set[Path] = set()
            for item in selected:
                p = Path(item.media_path).resolve()
                if not p.is_file():
                    failed += 1
                    continue
                try:
                    p.unlink()
                    deleted += 1
                    parents.add(p.parent)
                except OSError:
                    failed += 1
            for par in parents:
                self.store.invalidate_folder_cache(par)
            cur = self.current_subfolder_entry
            if cur is not None:
                self.render_subfolder_media(cur)
            self.set_status(f"已刪除 {deleted} 個檔案" + (f"，{failed} 個失敗" if failed else ""))
            return

        if self.current_view_mode != "entries":
            messagebox.showinfo("提示", "請在子資料夾預覽中選取要刪除的項目。")
            return

        selected_entries = [e for e in self.current_entries if self._item_key_for_entry(e) in self.selected_entry_keys]
        if not selected_entries and self._context_target is not None:
            selected_entries = [self._context_target]
        if not selected_entries:
            messagebox.showinfo("提示", "請先選取要刪除的資料夾。")
            return

        if self.store.root_folder and any(
            Path(e.subfolder_path).resolve() == Path(self.store.root_folder).resolve() for e in selected_entries
        ):
            messagebox.showwarning("警告", "不可刪除主資料夾。")
            return

        preview = "\n".join(e.subfolder_name for e in selected_entries[:15])
        extra = f"\n… 等共 {len(selected_entries)} 個資料夾" if len(selected_entries) > 15 else ""
        msg = f"即將永久刪除以下資料夾及其所有內容：\n\n{preview}{extra}"
        if not self._confirm_deletion_with_checkbox("刪除資料夾", msg):
            return

        tree_state = self._capture_tree_state()
        deleted_resolved: list[Path] = []
        deleted_n = 0
        failed = 0
        for entry in selected_entries:
            folder = Path(entry.subfolder_path).resolve()
            if self.store.root_folder and folder == Path(self.store.root_folder).resolve():
                failed += 1
                continue
            if not folder.is_dir():
                failed += 1
                continue
            try:
                rel = ""
                try:
                    rel = self.store.to_relative_key(folder)
                except Exception:
                    pass
                if rel:
                    self.tag_repo.remove_keys_by_prefix(rel)
                self.store.delete_folder(folder)
                self._tree_order_after_delete_folder(folder)
                deleted_resolved.append(folder.resolve())
                deleted_n += 1
            except Exception:
                failed += 1

        tree_state = self._prune_tree_state_after_deleted_paths(tree_state, deleted_resolved)
        self.selected_entry_keys.clear()
        self.refresh_tree(restore_state=tree_state)
        self.set_status(f"已刪除 {deleted_n} 個資料夾" + (f"，{failed} 個失敗" if failed else ""))

    def _build_entry_for_folder(self, folder: Path, person_name: str) -> SubfolderEntry:
        preview_path, preview_type, media_count = self.store.get_folder_media_info(folder)
        try:
            relative_key = self.store.to_relative_key(folder)
        except Exception:
            relative_key = ""
        return SubfolderEntry(
            person_name=person_name,
            subfolder_name=folder.name,
            subfolder_path=folder,
            relative_key=relative_key,
            preview_path=preview_path,
            preview_type=preview_type,
            media_count=media_count,
        )

    def _entry_for_tree_subfolder(self, payload: dict) -> SubfolderEntry:
        entry = payload.get("entry")
        if isinstance(entry, SubfolderEntry):
            return entry
        path = payload["path"]
        person_name = payload["person_name"]
        entry = self._build_entry_for_folder(Path(path), person_name)
        payload["entry"] = entry
        return entry

    @staticmethod
    def _invalid_name_chars() -> set[str]:
        return {'\\', '/', ':', '*', '?', '"', '<', '>', '|'}

    def _is_valid_folder_basename(self, name: str) -> bool:
        s = (name or "").strip()
        if not s or s in (".", ".."):
            return False
        return not any(c in s for c in self._invalid_name_chars())

    def _is_valid_file_stem(self, stem: str) -> bool:
        s = (stem or "").strip()
        if not s:
            return False
        return not any(c in s for c in self._invalid_name_chars())

    def _tree_state_after_folder_rename(self, old_path: Path, new_path: Path, state: dict) -> dict:
        old_key = self._path_key(old_path)
        new_key = self._path_key(new_path)
        try:
            old_r = Path(old_path).resolve()
            new_r = Path(new_path).resolve()
        except Exception:
            return dict(state)

        def rewrite_one(p: str) -> str:
            if p == old_key:
                return new_key
            try:
                cand = Path(p).resolve()
                rel = cand.relative_to(old_r)
                return self._path_key(new_r / rel)
            except ValueError:
                return p

        out = dict(state)
        sp = state.get("selected_path")
        if isinstance(sp, str):
            out["selected_path"] = rewrite_one(sp)
        ex = state.get("expanded_paths") or []
        out["expanded_paths"] = [rewrite_one(x) for x in ex]
        return out

    def _cancel_thumb_yview_debounce(self) -> None:
        if self._thumb_yview_after_id:
            try:
                self.root.after_cancel(self._thumb_yview_after_id)
            except Exception:
                pass
            self._thumb_yview_after_id = None

    def _ensure_thumbnail_scroll_hook(self) -> None:
        if self._thumb_scroll_hooked:
            return
        canvas = self.thumbnail_scroll._parent_canvas
        scrollbar = self.thumbnail_scroll._scrollbar

        try:
            scrollbar.configure(
                fg_color=self.ui_colors["panel2"],
                button_color=self.ui_colors["border"],
                button_hover_color="#cbd5e1",
            )
        except Exception:
            pass

        def yscroll_cmd(first: str, last: str) -> None:
            scrollbar.set(first, last)
            self._schedule_thumb_yview_check()

        canvas.configure(yscrollcommand=yscroll_cmd)
        self._thumb_scroll_hooked = True

    def _schedule_thumb_yview_check(self) -> None:
        self._cancel_thumb_yview_debounce()
        self._thumb_yview_after_id = self.root.after(THUMB_YVIEW_DEBOUNCE_MS, self._flush_thumb_yview_check)

    def _flush_thumb_yview_check(self) -> None:
        self._thumb_yview_after_id = None
        try:
            _, bottom = self.thumbnail_scroll._parent_canvas.yview()
        except Exception:
            return
        if bottom < THUMB_YVIEW_LOAD_THRESHOLD:
            return
        self._thumb_extend_from_scroll()
        self.root.after(40, self._try_fill_thumbnail_viewport)

    def _thumb_extend_from_scroll(self) -> None:
        st = self._thumb_paging_state
        if not st:
            return
        if not self._is_active_session(st["sid"]):
            return
        if st["kind"] == "entries" and st["next_index"] < len(st["entries"]):
            self._thumb_append_entries(st)
        elif st["kind"] == "media" and st["next_index"] < len(st["items"]):
            self._thumb_append_media(st)

    def _try_fill_thumbnail_viewport(self) -> None:
        st = self._thumb_paging_state
        if not st or not self._is_active_session(st["sid"]):
            return
        try:
            _, bottom = self.thumbnail_scroll._parent_canvas.yview()
        except Exception:
            return
        if bottom < 0.94:
            return
        if st["kind"] == "entries":
            if st["next_index"] >= len(st["entries"]):
                return
            self._thumb_append_entries(st)
            self.root.after(16, self._try_fill_thumbnail_viewport)
        elif st["kind"] == "media":
            if st["next_index"] >= len(st["items"]):
                return
            self._thumb_append_media(st)
            self.root.after(16, self._try_fill_thumbnail_viewport)

    def _thumb_append_entries(self, st: dict) -> None:
        sid = st["sid"]
        entries: list[SubfolderEntry] = st["entries"]
        start = st["next_index"]
        if not self._is_active_session(sid) or start >= len(entries):
            return
        batch_size = ENTRY_BATCH_FIRST if start == 0 else ENTRY_BATCH_SIZE
        end = min(start + batch_size, len(entries))
        for idx in range(start, end):
            entry = entries[idx]
            row = idx // ENTRY_COLUMNS
            col = idx % ENTRY_COLUMNS
            card, image_label = self._create_entry_card(row, col, entry)
            entry_key = self._item_key_for_entry(entry)
            self._entry_card_widgets[entry_key] = card
            self._bind_preview_card_selection(card, entry, idx, "entry")
            self._bind_preview_card_drag(card, entry, idx, "entry")
            self._bind_entry_card_double_click(card, entry)
            entry_menu = lambda e, x=entry: self.show_context_menu_for_entry(e, x)
            self._bind_right_click_menu(card, entry_menu)
            for child in card.winfo_children():
                self._bind_right_click_menu(child, entry_menu)
            fut = self.thumb_executor.submit(self.thumbnail_service.get_entry_thumbnail, entry)
            fut.add_done_callback(
                lambda f, session_id=sid, lbl=image_label: self._enqueue_ui_task(
                    self._apply_thumbnail, session_id, lbl, f, ENTRY_THUMBNAIL_SIZE
                )
            )
        st["next_index"] = end
        if end >= len(entries):
            self.set_status(f"已顯示全部 {len(entries)} 個子資料夾")
        else:
            self.set_status(f"顯示 {end}/{len(entries)} 個子資料夾（捲到底部載入更多）")

    def _thumb_append_media(self, st: dict) -> None:
        sid = st["sid"]
        media_items: list[MediaItem] = st["items"]
        tree_entry: SubfolderEntry = st["entry"]
        start = st["next_index"]
        if not self._is_active_session(sid) or start >= len(media_items):
            return
        batch_size = MEDIA_BATCH_FIRST if start == 0 else MEDIA_BATCH_SIZE
        end = min(start + batch_size, len(media_items))
        for idx in range(start, end):
            item = media_items[idx]
            row = idx // MEDIA_COLUMNS
            col = idx % MEDIA_COLUMNS
            card, image_label, duration_label = self._create_media_card(row, col, item)
            media_key = self._item_key_for_media(item)
            self._media_card_widgets[media_key] = card
            self._bind_preview_card_selection(card, item, idx, "media")
            self._bind_preview_card_drag(card, item, idx, "media")
            self._bind_media_card_context_menu(card, item)
            self._bind_media_card_double_click_open(card, item)
            fut = self.thumb_executor.submit(
                self.thumbnail_service.get_file_thumbnail, item.media_path, item.media_type, MEDIA_THUMBNAIL_SIZE
            )
            fut.add_done_callback(
                lambda f, session_id=sid, lbl=image_label: self._enqueue_ui_task(
                    self._apply_thumbnail, session_id, lbl, f, MEDIA_THUMBNAIL_SIZE
                )
            )
            if duration_label is not None:
                fut_dur = self.thumb_executor.submit(
                    self.thumbnail_service.get_video_duration_seconds, item.media_path
                )
                fut_dur.add_done_callback(
                    lambda f, session_id=sid, lbl=duration_label: self._enqueue_ui_task(
                        self._apply_video_duration, session_id, lbl, f
                    )
                )
        st["next_index"] = end
        if end >= len(media_items):
            self.set_status(f"已顯示全部 {len(media_items)} 個媒體檔案")
        else:
            self.set_status(f"顯示 {end}/{len(media_items)} 個媒體檔案（捲到底部載入更多）")

    def _merged_entries_background(self) -> tuple[list[SubfolderEntry], dict[str, list[SubfolderEntry]]]:
        per_person: dict[str, list[SubfolderEntry]] = {}
        merged: list[SubfolderEntry] = []
        for person_folder in self._get_ordered_people_folders():
            entries = self._order_entries_by_saved_tree(
                person_folder, self.store.get_subfolder_entries_shallow(person_folder)
            )
            per_person[person_folder.name] = entries
            merged.extend(entries)
        return merged, per_person

    def _begin_load_merged_entries(self) -> None:
        sid = self._new_session()
        self.current_view_mode = "entries_pending"
        self.current_subfolder_entry = None
        self.current_media_items = []
        self.current_entries = []
        self.scope_label.configure(text=f"目前檢視：{self.current_scope_label}")
        self.clear_thumbnail_cards()
        ctk.CTkLabel(self.thumbnail_scroll, text="載入全部人物的子資料夾清單…", anchor="w").grid(
            row=0, column=0, padx=12, pady=12, sticky="w"
        )
        self.set_status("掃描各人物資料夾…")
        fut = self.scan_executor.submit(self._merged_entries_background)
        fut.add_done_callback(
            lambda f, session_id=sid: self._enqueue_ui_task(self._on_merged_entries_loaded, session_id, f)
        )

    def _on_merged_entries_loaded(self, sid: int, future) -> None:
        if not self._is_active_session(sid):
            return
        try:
            merged, per_person = future.result()
        except Exception as exc:
            messagebox.showerror("錯誤", f"載入清單失敗：\n{exc}")
            return
        self.person_entries.clear()
        self.person_entries.update(per_person)
        self.render_entries(merged, reuse_session=sid)

    def _begin_load_person_entries(self, person_folder: Path) -> None:
        sid = self._new_session()
        self.current_view_mode = "entries_pending"
        self.current_subfolder_entry = None
        self.current_media_items = []
        self.current_entries = []
        self.scope_label.configure(text=f"目前檢視：{self.current_scope_label}")
        self.clear_thumbnail_cards()
        ctk.CTkLabel(self.thumbnail_scroll, text="載入子資料夾清單中…", anchor="w").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        self.set_status("掃描子資料夾中…")
        fut = self.scan_executor.submit(self.store.get_subfolder_entries_shallow, person_folder)
        fut.add_done_callback(
            lambda f, session_id=sid, pf=person_folder: self._enqueue_ui_task(
                self._on_shallow_entries_loaded_for_person, session_id, pf, f
            )
        )

    def _on_shallow_entries_loaded_for_person(self, sid: int, person_folder: Path, future) -> None:
        if not self._is_active_session(sid):
            return
        try:
            entries = future.result()
        except Exception as exc:
            messagebox.showerror("錯誤", f"載入子資料夾清單失敗：\n{exc}")
            return
        entries = self._order_entries_by_saved_tree(person_folder, entries)
        self.person_entries[person_folder.name] = entries
        self.render_entries(entries, reuse_session=sid)

    def on_tree_select(self, _event=None) -> None:
        if self._suppress_tree_select_once:
            self._suppress_tree_select_once = False
            return
        selected = self.folder_tree.selection()
        if not selected:
            return
        self._pending_selected_item = selected[0]
        if self._pending_select_after_id:
            self.root.after_cancel(self._pending_select_after_id)
        self._pending_select_after_id = self.root.after(self.selection_debounce_ms, self._process_tree_selection)

    def _process_tree_selection(self) -> None:
        self._pending_select_after_id = None
        if not self._pending_selected_item:
            return
        item_id = self._pending_selected_item
        self._pending_selected_item = None
        self._apply_tree_selection_from_item_id(item_id)

    def _apply_tree_selection_from_item_id(self, item_id: str) -> None:
        payload = self.tree_metadata.get(item_id)
        if not payload:
            return

        node_type = payload.get("type")
        if node_type == "root":
            self.current_scope_label = "全部人物"
            self.current_scope_path = Path(payload["path"]).resolve() if payload.get("path") else None
            if self.selected_filter_tags:
                merged_tf: list[SubfolderEntry] = []
                for entries in self.person_entries.values():
                    merged_tf.extend(entries)
                self.render_entries(merged_tf)
            else:
                people = self._get_ordered_people_folders()
                want = {p.name for p in people}
                if want and want == set(self.person_entries.keys()):
                    merged: list[SubfolderEntry] = []
                    for p in people:
                        merged.extend(self.person_entries[p.name])
                    self.render_entries(merged)
                else:
                    self._begin_load_merged_entries()
        elif node_type == "person":
            person_folder = payload["path"]
            self.current_scope_label = person_folder.name
            self.current_scope_path = Path(person_folder).resolve()
            cached = self.person_entries.get(person_folder.name)
            if cached is not None:
                self.render_entries(cached)
            else:
                self._begin_load_person_entries(person_folder)
        elif node_type == "subfolder":
            entry = self._entry_for_tree_subfolder(payload)
            self.current_scope_label = f"{entry.person_name} / {entry.subfolder_name}"
            self.current_scope_path = Path(entry.subfolder_path).resolve()
            self.render_subfolder_media(entry)
        self._update_back_buttons_state()

    def clear_thumbnail_cards(self) -> None:
        self._cancel_thumb_yview_debounce()
        self._thumb_paging_state = None
        self._drag_state = None
        self._hide_drag_hint()
        self._hide_insert_indicator()
        self.selected_entry_keys.clear()
        self.selected_media_paths.clear()
        self._entry_card_widgets.clear()
        self._media_card_widgets.clear()
        self._selection_anchor_index = None
        for child in self.thumbnail_scroll.winfo_children():
            child.destroy()
        self._reset_preview_scroll_top()

    @staticmethod
    def _is_macos_platform() -> bool:
        return sys.platform == "darwin"

    @staticmethod
    def _item_key_for_entry(entry: SubfolderEntry) -> str:
        return str(Path(entry.subfolder_path).resolve())

    @staticmethod
    def _item_key_for_media(item: MediaItem) -> str:
        return str(Path(item.media_path).resolve())

    def _apply_card_selected_style(self, card: ctk.CTkFrame, selected: bool) -> None:
        try:
            if selected:
                card.configure(border_width=2, border_color="#3B8ED0")
            else:
                card.configure(border_width=0)
        except Exception:
            return

    def _refresh_preview_selection_styles(self) -> None:
        for key, card in self._entry_card_widgets.items():
            self._apply_card_selected_style(card, key in self.selected_entry_keys)
        for key, card in self._media_card_widgets.items():
            self._apply_card_selected_style(card, key in self.selected_media_paths)

    def _selection_keys_order(self) -> list[str]:
        st = self._thumb_paging_state or {}
        kind = st.get("kind")
        if kind == "media":
            return [self._item_key_for_media(x) for x in st.get("items", [])]
        if kind == "entries":
            return [self._item_key_for_entry(x) for x in st.get("entries", [])]
        if self.current_view_mode == "media":
            return [self._item_key_for_media(x) for x in self.current_media_items]
        return [self._item_key_for_entry(x) for x in self.current_entries]

    def _bind_preview_card_selection(self, card: ctk.CTkFrame, item, idx: int, kind: str) -> None:
        def get_key() -> str:
            if kind == "entry":
                return self._item_key_for_entry(item)
            return self._item_key_for_media(item)

        def select_single(_event: tk.Event) -> None:
            key = get_key()
            # 拖曳多選群組時，按在既有選取項上不先清空成單選
            if kind == "entry" and len(self.selected_entry_keys) > 1 and key in self.selected_entry_keys:
                return
            if kind == "media" and len(self.selected_media_paths) > 1 and key in self.selected_media_paths:
                return
            if kind == "entry":
                self.selected_entry_keys = {key}
                self.selected_media_paths.clear()
            else:
                self.selected_media_paths = {key}
                self.selected_entry_keys.clear()
            self._selection_anchor_index = idx
            self._refresh_preview_selection_styles()

        def toggle_one(_event: tk.Event) -> str:
            key = get_key()
            if kind == "entry":
                self.selected_media_paths.clear()
                if key in self.selected_entry_keys:
                    self.selected_entry_keys.remove(key)
                else:
                    self.selected_entry_keys.add(key)
            else:
                self.selected_entry_keys.clear()
                if key in self.selected_media_paths:
                    self.selected_media_paths.remove(key)
                else:
                    self.selected_media_paths.add(key)
            self._selection_anchor_index = idx
            self._refresh_preview_selection_styles()
            return "break"

        def select_range(_event: tk.Event) -> str:
            anchor = self._selection_anchor_index if self._selection_anchor_index is not None else idx
            lo, hi = sorted((anchor, idx))
            keys = self._selection_keys_order()
            picked = set(keys[lo : hi + 1])
            if kind == "entry":
                self.selected_entry_keys = picked
                self.selected_media_paths.clear()
            else:
                self.selected_media_paths = picked
                self.selected_entry_keys.clear()
            self._refresh_preview_selection_styles()
            return "break"

        def bind_tree(w: tk.Misc) -> None:
            w.bind("<Button-1>", select_single)
            w.bind("<Shift-Button-1>", select_range)
            if self._is_macos_platform():
                w.bind("<Command-Button-1>", toggle_one)
            else:
                w.bind("<Control-Button-1>", toggle_one)
            for ch in w.winfo_children():
                bind_tree(ch)

        bind_tree(card)

    def _ensure_selected_for_drag(self, kind: str, item_key: str, idx: int) -> None:
        if kind == "entry":
            if item_key not in self.selected_entry_keys:
                self.selected_entry_keys = {item_key}
                self.selected_media_paths.clear()
        else:
            if item_key not in self.selected_media_paths:
                self.selected_media_paths = {item_key}
                self.selected_entry_keys.clear()
        self._selection_anchor_index = idx
        self._refresh_preview_selection_styles()

    def _preview_selected_keys(self, kind: str) -> set[str]:
        return set(self.selected_entry_keys if kind == "entry" else self.selected_media_paths)

    def _show_drag_hint(self, text: str, x_root: int, y_root: int) -> None:
        self._hide_drag_hint()
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        try:
            win.attributes("-alpha", 0.72)
        except tk.TclError:
            pass
        label = tk.Label(
            win,
            text=text,
            bg=self.ui_colors["accent"],
            fg="white",
            padx=10,
            pady=6,
            font=(self._platform_font_family(), 11, "bold"),
        )
        label.pack()
        win.geometry(f"+{x_root + 14}+{y_root + 14}")
        self._drag_hint_win = win

    def _move_drag_hint(self, x_root: int, y_root: int) -> None:
        if self._drag_hint_win is None:
            return
        try:
            self._drag_hint_win.geometry(f"+{x_root + 14}+{y_root + 14}")
        except tk.TclError:
            self._drag_hint_win = None

    def _hide_drag_hint(self) -> None:
        if self._drag_hint_win is None:
            return
        try:
            self._drag_hint_win.destroy()
        except Exception:
            pass
        self._drag_hint_win = None

    def _ensure_insert_indicator(self) -> tk.Frame:
        if self._insert_indicator is None or not self._insert_indicator.winfo_exists():
            self._insert_indicator = tk.Frame(
                self.thumbnail_scroll, bg=self.ui_colors["accent"], width=3, height=12, bd=0, highlightthickness=0
            )
        return self._insert_indicator

    def _hide_insert_indicator(self) -> None:
        if self._insert_indicator is None:
            return
        try:
            self._insert_indicator.place_forget()
        except Exception:
            pass

    def _preview_cards_in_order(self, kind: str, ordered_keys: list[str]) -> list[ctk.CTkFrame]:
        mapping = self._entry_card_widgets if kind == "entry" else self._media_card_widgets
        out: list[ctk.CTkFrame] = []
        for key in ordered_keys:
            card = mapping.get(key)
            if card is not None and card.winfo_exists():
                out.append(card)
        return out

    def _compute_drop_index(self, kind: str, x_root: int, y_root: int, ordered_keys: list[str]) -> int:
        cards = self._preview_cards_in_order(kind, ordered_keys)
        if not cards:
            return 0
        frame_x = self.thumbnail_scroll.winfo_rootx()
        frame_y = self.thumbnail_scroll.winfo_rooty()
        x = x_root - frame_x
        y = y_root - frame_y
        centers: list[tuple[float, int, ctk.CTkFrame]] = []
        for i, c in enumerate(cards):
            cx = c.winfo_x() + (c.winfo_width() / 2)
            cy = c.winfo_y() + (c.winfo_height() / 2)
            d = (cx - x) ** 2 + (cy - y) ** 2
            centers.append((d, i, c))
        centers.sort(key=lambda t: t[0])
        _, nearest_index, nearest_card = centers[0]
        before = x < (nearest_card.winfo_x() + nearest_card.winfo_width() / 2)
        insert_index = nearest_index if before else nearest_index + 1

        ind = self._ensure_insert_indicator()
        if insert_index >= len(cards):
            ref = cards[-1]
            px = ref.winfo_x() + ref.winfo_width() + 4
            py = ref.winfo_y() + 6
            ph = max(10, ref.winfo_height() - 12)
        else:
            ref = cards[insert_index]
            px = max(4, ref.winfo_x() - 4)
            py = ref.winfo_y() + 6
            ph = max(10, ref.winfo_height() - 12)
        ind.place(x=px, y=py, width=3, height=ph)
        return max(0, min(insert_index, len(ordered_keys)))

    @staticmethod
    def _reorder_by_keys(items: list, item_keys: list[str], selected_keys: set[str], insert_index: int) -> list:
        selected_pairs = [(it, k) for it, k in zip(items, item_keys) if k in selected_keys]
        remain_pairs = [(it, k) for it, k in zip(items, item_keys) if k not in selected_keys]
        before_count = sum(1 for i, k in enumerate(item_keys[:insert_index]) if k in selected_keys)
        target = max(0, min(len(remain_pairs), insert_index - before_count))
        new_pairs = remain_pairs[:target] + selected_pairs + remain_pairs[target:]
        return [p[0] for p in new_pairs]

    def _render_media_from_current_items(self, reuse_session: Optional[int] = None) -> None:
        sid = reuse_session if reuse_session is not None else self._new_session()
        entry = self.current_subfolder_entry
        if entry is None:
            return
        display_items = self._sorted_media_for_preview(list(self.current_media_items))
        self.clear_thumbnail_cards()
        if not display_items:
            ctk.CTkLabel(self.thumbnail_scroll, text="目前篩選條件下沒有符合的媒體項目").grid(
                row=0, column=0, padx=16, pady=16, sticky="w"
            )
            return
        for col in range(MEDIA_COLUMNS):
            self.thumbnail_scroll.grid_columnconfigure(col, weight=1)
        self._ensure_thumbnail_scroll_hook()
        self._thumb_paging_state = {"sid": sid, "kind": "media", "items": display_items, "entry": entry, "next_index": 0}
        self._thumb_append_media(self._thumb_paging_state)
        self.root.after(16, self._try_fill_thumbnail_viewport)

    def _bind_preview_card_drag(self, card: ctk.CTkFrame, item, idx: int, kind: str) -> None:
        SHIFT_MASK = 0x0001

        def key_of() -> str:
            return self._item_key_for_entry(item) if kind == "entry" else self._item_key_for_media(item)

        def selected_paths_for_drag() -> list[str]:
            if kind == "entry":
                keys = set(self.selected_entry_keys)
                if not keys:
                    return []
                return sorted(keys)
            keys = set(self.selected_media_paths)
            if not keys:
                return []
            return sorted(keys)

        def drag_init(event: tk.Event):
            if not self._dnd_available or DND_FILES is None or COPY is None:
                return None
            key = key_of()
            self._ensure_selected_for_drag(kind, key, idx)
            paths = selected_paths_for_drag()
            if not paths:
                return None
            data = tuple(paths)
            return (COPY, DND_FILES, data)

        def drag_end(_event: tk.Event):
            return None

        def on_press(event: tk.Event) -> None:
            key = key_of()
            self._ensure_selected_for_drag(kind, key, idx)
            if not (event.state & SHIFT_MASK):
                self._drag_state = None
                return
            self._drag_state = {
                "kind": kind,
                "start_x_root": event.x_root,
                "start_y_root": event.y_root,
                "dragging": False,
                "insert_index": None,
            }

        def on_motion(event: tk.Event) -> None:
            if not (event.state & SHIFT_MASK):
                return
            st = self._drag_state
            if not st or st.get("kind") != kind:
                return
            dx = abs(event.x_root - st["start_x_root"])
            dy = abs(event.y_root - st["start_y_root"])
            if not st["dragging"] and (dx + dy) < 8:
                return
            if not st["dragging"]:
                st["dragging"] = True
                count = len(self._preview_selected_keys(kind))
                self._show_drag_hint(f"移動 {count} 個項目", event.x_root, event.y_root)
            self._move_drag_hint(event.x_root, event.y_root)
            keys_order = self._selection_keys_order()
            st["insert_index"] = self._compute_drop_index(kind, event.x_root, event.y_root, keys_order)

        def on_release(_event: tk.Event) -> None:
            st = self._drag_state
            self._drag_state = None
            if not st:
                self._hide_drag_hint()
                self._hide_insert_indicator()
                return
            dragging = bool(st.get("dragging"))
            insert_index = st.get("insert_index")
            self._hide_drag_hint()
            self._hide_insert_indicator()
            if not dragging or insert_index is None:
                return
            if kind == "entry":
                st2 = self._thumb_paging_state or {}
                items = list(st2.get("entries", self.current_entries))
                keys = [self._item_key_for_entry(x) for x in items]
                selected = set(self.selected_entry_keys)
                if not selected:
                    return
                reordered = self._reorder_by_keys(items, keys, selected, int(insert_index))
                self.current_entries = reordered
                self.render_entries(self.current_entries)
            else:
                st2 = self._thumb_paging_state or {}
                items = list(st2.get("items", self.current_media_items))
                keys = [self._item_key_for_media(x) for x in items]
                selected = set(self.selected_media_paths)
                if not selected:
                    return
                self.current_media_items = self._reorder_by_keys(items, keys, selected, int(insert_index))
                self._render_media_from_current_items()

        def bind_tree(w: tk.Misc) -> None:
            w.bind("<ButtonPress-1>", on_press, add="+")
            w.bind("<B1-Motion>", on_motion, add="+")
            w.bind("<ButtonRelease-1>", on_release, add="+")
            if self._dnd_available:
                try:
                    w.drag_source_register(1, DND_FILES)
                    w.dnd_bind("<<DragInitCmd>>", drag_init)
                    w.dnd_bind("<<DragEndCmd>>", drag_end)
                except Exception:
                    pass
            for ch in w.winfo_children():
                bind_tree(ch)

        bind_tree(card)

    def _bind_entry_card_double_click(self, card: ctk.CTkFrame, entry: SubfolderEntry) -> None:
        def on_double(_event: tk.Event, e: SubfolderEntry = entry) -> None:
            self._open_entry_from_preview(e)

        def bind_tree(w: tk.Misc) -> None:
            w.bind("<Double-1>", on_double, add="+")
            for ch in w.winfo_children():
                bind_tree(ch)

        bind_tree(card)

    def render_entries(self, entries: list[SubfolderEntry], *, reuse_session: Optional[int] = None) -> None:
        sid = reuse_session if reuse_session is not None else self._new_session()
        self.current_view_mode = "entries"
        self.current_subfolder_entry = None
        self.current_entries = list(entries)
        self.current_media_items = []
        self.scope_label.configure(text=f"目前檢視：{self.current_scope_label}")
        self._update_back_buttons_state()
        filtered = self._apply_media_entry_filter(self._apply_tag_filter(entries))
        filtered = self._sorted_entries_for_preview(list(filtered))
        self.clear_thumbnail_cards()
        if not filtered:
            ctk.CTkLabel(self.thumbnail_scroll, text="沒有可顯示的子資料夾").grid(
                row=0, column=0, padx=16, pady=16, sticky="w"
            )
            self.set_status("目前標籤／媒體類型篩選下沒有結果")
            return
        for col in range(ENTRY_COLUMNS):
            self.thumbnail_scroll.grid_columnconfigure(col, weight=0, minsize=ENTRY_CARD_SIZE[0] + 16)
        self._ensure_thumbnail_scroll_hook()
        self._thumb_paging_state = {"sid": sid, "kind": "entries", "entries": filtered, "next_index": 0}
        self._thumb_append_entries(self._thumb_paging_state)
        self.root.after(16, self._try_fill_thumbnail_viewport)

    def _create_entry_card(self, row: int, col: int, entry: SubfolderEntry):
        card = ctk.CTkFrame(self.thumbnail_scroll, fg_color=self.ui_colors["panel"])
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nw")
        card.configure(width=ENTRY_CARD_SIZE[0], height=ENTRY_CARD_SIZE[1])
        card.grid_propagate(False)
        card.grid_rowconfigure(0, weight=0)
        card.grid_rowconfigure(1, weight=0)
        card.grid_rowconfigure(2, weight=0)
        card.grid_rowconfigure(3, weight=0)
        card.grid_columnconfigure(0, weight=1)

        holder = self.thumbnail_service._build_placeholder("LOADING", ENTRY_THUMBNAIL_SIZE)
        image = ctk.CTkImage(light_image=holder, dark_image=holder, size=ENTRY_THUMBNAIL_SIZE)
        image_label = ctk.CTkLabel(card, text="", image=image, width=ENTRY_THUMBNAIL_SIZE[0], height=ENTRY_THUMBNAIL_SIZE[1])
        image_label.image_ref = image
        image_label.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="w")

        title = entry.subfolder_name if len(entry.subfolder_name) <= 24 else entry.subfolder_name[:24] + "..."
        ctk.CTkLabel(card, text=title, anchor="w", font=self.font_base_bold, height=24, text_color=self.ui_colors["text"]).grid(
            row=1, column=0, padx=8, sticky="ew"
        )
        tags_text = ", ".join(self.tag_repo.get_effective_tags(entry.relative_key)) or "（尚未標籤）"
        if len(tags_text) > 30:
            tags_text = tags_text[:30] + "..."
        ctk.CTkLabel(card, text=f"標籤：{tags_text}", anchor="w", height=16, font=self.font_small, text_color=self.ui_colors["muted"]).grid(
            row=2, column=0, padx=8, pady=(0, 1), sticky="ew"
        )
        ctk.CTkLabel(
            card,
            text=f"媒體數量：{entry.media_count}",
            anchor="w",
            height=20,
            font=self.font_small,
            text_color=self.ui_colors["muted"],
        ).grid(row=3, column=0, padx=8, pady=(0, 8), sticky="ew")
        return card, image_label

    def render_subfolder_media(self, entry: SubfolderEntry) -> None:
        try:
            d_lo, d_hi = self._parse_duration_filter_minutes()
        except ValueError as exc:
            messagebox.showerror("影片長度篩選", str(exc))
            self.set_status(str(exc))
            return
        sid = self._new_session()
        self.current_view_mode = "media"
        self.current_subfolder_entry = entry
        self.current_entries = [entry]
        self.current_scope_label = f"{entry.person_name} / {entry.subfolder_name}"
        self.scope_label.configure(text=f"目前檢視：{self.current_scope_label}（媒體預覽）")
        self._update_back_buttons_state()
        self.clear_thumbnail_cards()
        self.current_media_items = []
        ctk.CTkLabel(self.thumbnail_scroll, text="載入中...").grid(
            row=0, column=0, padx=12, pady=12, sticky="w"
        )
        self.set_status("正在掃描子資料夾媒體...")

        start = self._perf_start()
        fut = self.scan_executor.submit(
            self._scan_media_for_preview_worker,
            entry.subfolder_path,
            self.filter_media_video_var.get(),
            self.filter_media_image_var.get(),
            d_lo,
            d_hi,
        )
        fut.add_done_callback(
            lambda f, session_id=sid, parent_entry=entry, s=start: self._enqueue_ui_task(
                self._on_media_items_loaded, session_id, parent_entry, f, s
            )
        )

    def _on_media_items_loaded(self, sid: int, entry: SubfolderEntry, future, scan_start: float) -> None:
        if not self._is_active_session(sid):
            return
        cur = self.current_subfolder_entry
        if cur is None:
            return
        try:
            if Path(entry.subfolder_path).resolve() != Path(cur.subfolder_path).resolve():
                return
        except Exception:
            return
        self.clear_thumbnail_cards()
        try:
            media_items, display_items = future.result()
        except Exception as exc:
            messagebox.showerror("錯誤", f"載入媒體清單失敗：\n{exc}")
            return
        display_items = self._sorted_media_for_preview(list(display_items))
        self.current_media_items = display_items
        if not media_items:
            ctk.CTkLabel(self.thumbnail_scroll, text="此子資料夾內沒有圖片或影片").grid(
                row=0, column=0, padx=16, pady=16, sticky="w"
            )
            self.set_status("子資料夾內沒有可預覽媒體")
            return
        if not display_items:
            ctk.CTkLabel(self.thumbnail_scroll, text="目前篩選條件下沒有符合的媒體項目").grid(
                row=0, column=0, padx=16, pady=16, sticky="w"
            )
            self.set_status("篩選後沒有可預覽媒體")
            return
        for col in range(MEDIA_COLUMNS):
            self.thumbnail_scroll.grid_columnconfigure(col, weight=1)
        self._perf_log("media_items_scan_done", scan_start, extra=f"count={len(display_items)}")
        self._ensure_thumbnail_scroll_hook()
        self._thumb_paging_state = {"sid": sid, "kind": "media", "items": display_items, "entry": entry, "next_index": 0}
        self._thumb_append_media(self._thumb_paging_state)
        self.root.after(16, self._try_fill_thumbnail_viewport)

    def _create_media_card(self, row: int, col: int, item: MediaItem):
        card = ctk.CTkFrame(self.thumbnail_scroll, fg_color=self.ui_colors["panel"])
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        card.configure(width=MEDIA_CARD_SIZE[0], height=MEDIA_CARD_SIZE[1])
        card.grid_propagate(False)
        card.grid_rowconfigure(0, weight=0)
        card.grid_rowconfigure(1, weight=0)
        card.grid_rowconfigure(2, weight=0)
        card.grid_rowconfigure(3, weight=0)
        card.grid_columnconfigure(0, weight=1)

        holder = self.thumbnail_service._build_placeholder("LOADING", MEDIA_THUMBNAIL_SIZE)
        image = ctk.CTkImage(light_image=holder, dark_image=holder, size=MEDIA_THUMBNAIL_SIZE)
        image_label = ctk.CTkLabel(card, text="", image=image, width=MEDIA_THUMBNAIL_SIZE[0], height=MEDIA_THUMBNAIL_SIZE[1])
        image_label.image_ref = image
        image_label.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="n")

        short_name = item.media_path.name if len(item.media_path.name) <= 28 else item.media_path.name[:28] + "..."
        ctk.CTkLabel(card, text=short_name, anchor="w", font=self.font_base_bold, text_color=self.ui_colors["text"]).grid(
            row=1, column=0, padx=8, sticky="ew"
        )
        ctk.CTkLabel(
            card,
            text=f"類型：{'圖片' if item.media_type == 'image' else '影片'}",
            anchor="w",
            height=20,
            font=self.font_small,
            text_color=self.ui_colors["muted"],
        ).grid(row=2, column=0, padx=8, pady=(2, 4), sticky="ew")
        duration_label = None
        if item.media_type == "video":
            duration_label = ctk.CTkLabel(
                card, text="長度：讀取中…", anchor="w", height=20, font=self.font_small, text_color=self.ui_colors["muted"]
            )
            duration_label.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="ew")
        return card, image_label, duration_label

    def _bind_media_card_context_menu(self, card: ctk.CTkFrame, item: MediaItem) -> None:
        def handler(event: tk.Event, m: MediaItem = item) -> None:
            self.show_context_menu_for_media(event, m)

        self._bind_right_click_menu(card, handler)
        for child in card.winfo_children():
            self._bind_right_click_menu(child, handler)

    def _bind_media_card_double_click_open(self, card: ctk.CTkFrame, item: MediaItem) -> None:
        def on_double(_event: tk.Event, m: MediaItem = item) -> None:
            self.open_media_browser(m)

        def bind_tree(w: tk.Misc) -> None:
            w.bind("<Double-1>", on_double)
            for ch in w.winfo_children():
                bind_tree(ch)

        bind_tree(card)

    def _open_path_in_default_app(self, path: Path) -> None:
        p = Path(path)
        if not p.is_file():
            messagebox.showerror("無法開啟", f"找不到檔案：\n{p}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(p))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(p)], check=False)
            else:
                subprocess.run(["xdg-open", str(p)], check=False)
        except Exception as exc:
            messagebox.showerror("無法開啟", str(exc))

    def open_media_browser(self, item: MediaItem) -> None:
        if self.current_view_mode != "media" or not self.current_media_items:
            messagebox.showinfo("提示", "請先進入子資料夾的媒體預覽，再雙擊檔案。")
            return
        items = list(self.current_media_items)
        key = item.media_path.resolve()
        try:
            idx = next(i for i, m in enumerate(items) if m.media_path.resolve() == key)
        except StopIteration:
            messagebox.showinfo("提示", "此檔案不在目前預覽清單中（可能已篩選排除）。")
            return
        prev = self._active_media_browser
        if prev is not None:
            prev.close()
        self._active_media_browser = MediaBrowserWindow(self, items, idx)

    def _apply_thumbnail(
        self, sid: int, image_label: ctk.CTkLabel, future, display_size: tuple[int, int]
    ) -> None:
        if not self._is_active_session(sid):
            return
        try:
            image = future.result()
        except Exception:
            image = self.thumbnail_service._build_placeholder("THUMB ERR", display_size)
        try:
            if getattr(image, "width", 0) <= 0 or getattr(image, "height", 0) <= 0:
                image = self.thumbnail_service._build_placeholder("THUMB ERR", display_size)
        except Exception:
            image = self.thumbnail_service._build_placeholder("THUMB ERR", display_size)
        try:
            ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=display_size)
            image_label.configure(image=ctk_image)
            image_label.image_ref = ctk_image
        except tk.TclError:
            return
        except Exception:
            return
        if not self.session_first_thumb_logged.get(sid, False):
            self.session_first_thumb_logged[sid] = True
            if self.profile_enabled:
                print(f"[PERF] first_thumbnail_ready(session={sid})")

    def _apply_video_duration(self, sid: int, duration_label: ctk.CTkLabel, future) -> None:
        if not self._is_active_session(sid):
            return
        try:
            seconds = future.result()
        except Exception:
            seconds = None
        if seconds is None or seconds <= 0:
            text = "長度：無法取得"
        else:
            text = f"長度：{ThumbnailService.format_video_duration(seconds)}"
        try:
            duration_label.configure(text=text)
        except tk.TclError:
            return

    def refresh_filter_panel(self) -> None:
        known_tags = self.tag_repo.get_all_tags()
        self.selected_filter_tags = {x for x in self.selected_filter_tags if x in known_tags}
        for child in self.filter_tags_container.winfo_children():
            child.destroy()
        self.filter_vars.clear()
        if not known_tags:
            ctk.CTkLabel(self.filter_tags_container, text="尚無標籤，可先對子資料夾使用「添加標籤」").pack(anchor="w", padx=4, pady=6)
            return
        for index, tag in enumerate(known_tags):
            row = index // 6
            col = index % 6
            cell = ctk.CTkFrame(self.filter_tags_container, fg_color="transparent")
            cell.grid(row=row, column=col, padx=(6, 10), pady=2, sticky="w")

            var = ctk.BooleanVar(value=tag in self.selected_filter_tags)
            self.filter_vars[tag] = var
            ctk.CTkCheckBox(
                cell, text=tag, variable=var, command=self.on_filter_changed, width=100, font=self.font_small
            ).pack(
                side="left", padx=(0, 0)
            )
            ctk.CTkButton(
                cell,
                text="×",
                width=24,
                height=22,
                fg_color="#ef4444",
                hover_color="#dc2626",
                font=self.font_icon,
                command=lambda t=tag: self.on_delete_tag_from_panel(t),
            ).pack(side="left", padx=(16, 2))

    def on_delete_tag_from_panel(self, tag: str) -> None:
        if not messagebox.askyesno(
            "刪除標籤",
            f"確定要從所有資料夾移除標籤「{tag}」嗎？\n\n此操作會更新標籤儲存檔，且無法復原。",
        ):
            return
        count = self.tag_repo.remove_tag_everywhere(tag)
        self.selected_filter_tags.discard(tag)
        media_snap = self._snapshot_media_view()
        self.refresh_tree(restore_state=self._capture_tree_state())
        self._restore_media_view_if_needed(media_snap)
        self.set_status(f"已刪除標籤「{tag}」（影響 {count} 筆資料夾記錄）")

    def on_filter_changed(self) -> None:
        self.selected_filter_tags = {tag for tag, var in self.filter_vars.items() if var.get()}
        self._refresh_tree_and_reload_selection()

    def _apply_tag_filter(self, entries: list[SubfolderEntry]) -> list[SubfolderEntry]:
        if not self.selected_filter_tags:
            return entries
        result: list[SubfolderEntry] = []
        for entry in entries:
            tags = set(self.tag_repo.get_effective_tags(entry.relative_key))
            if tags.intersection(self.selected_filter_tags):
                result.append(entry)
        return result

    def on_tree_right_click(self, event) -> None:
        row = self.folder_tree.identify_row(event.y)
        if not row:
            return
        self.folder_tree.selection_set(row)
        payload = self.tree_metadata.get(row)
        if not payload:
            return
        self._context_media_item = None
        node_type = payload.get("type")
        if node_type == "stub":
            return
        if node_type == "root":
            root_folder = payload.get("path")
            root_entry = SubfolderEntry(
                person_name=root_folder.name,
                subfolder_name=root_folder.name,
                subfolder_path=root_folder,
                relative_key="",
                preview_path=None,
                preview_type=None,
                media_count=0,
            )
            self._context_target = root_entry
            self.context_menu.entryconfig("新增資料夾…", state="normal")
            self.context_menu.entryconfig("添加標籤", state="disabled")
            self.context_menu.entryconfig("打開目標資料夾", state="normal")
            self.context_menu.entryconfig("重新命名資料夾", state="disabled")
            self.context_menu.entryconfig("重新命名檔案", state="disabled")
            self.context_menu.entryconfig("轉移資料夾內容到…", state="disabled")
            self.context_menu.entryconfig("轉移已選取項目到…", state="disabled")
            self.context_menu.entryconfig("轉移並建立新資料夾…", state="disabled")
            self.context_menu.entryconfig("重新命名與添加序號…", state="disabled")
            self.context_menu.entryconfig("刪除選取的檔案或資料夾…", state="disabled")
            self.context_menu.entryconfig("刪除資料夾", state="disabled")
        elif node_type == "subfolder":
            self._context_target = self._entry_for_tree_subfolder(payload)
            self.context_menu.entryconfig("新增資料夾…", state="normal")
            self.context_menu.entryconfig("添加標籤", state="normal")
            self.context_menu.entryconfig("打開目標資料夾", state="normal")
            self.context_menu.entryconfig("重新命名資料夾", state="normal")
            self.context_menu.entryconfig("重新命名檔案", state="disabled")
            self.context_menu.entryconfig("轉移資料夾內容到…", state="normal")
            self.context_menu.entryconfig("轉移已選取項目到…", state="disabled")
            self.context_menu.entryconfig("轉移並建立新資料夾…", state="disabled")
            self.context_menu.entryconfig("重新命名與添加序號…", state="disabled")
            self.context_menu.entryconfig("刪除選取的檔案或資料夾…", state="disabled")
            self.context_menu.entryconfig("刪除資料夾", state="normal")
        elif node_type == "person":
            person_folder = payload.get("path")
            person_entry = SubfolderEntry(
                person_name=person_folder.name,
                subfolder_name=person_folder.name,
                subfolder_path=person_folder,
                relative_key="",
                preview_path=None,
                preview_type=None,
                media_count=0,
            )
            self._context_target = person_entry
            self.context_menu.entryconfig("新增資料夾…", state="normal")
            self.context_menu.entryconfig("添加標籤", state="disabled")
            self.context_menu.entryconfig("打開目標資料夾", state="normal")
            self.context_menu.entryconfig("重新命名資料夾", state="normal")
            self.context_menu.entryconfig("重新命名檔案", state="disabled")
            self.context_menu.entryconfig("轉移資料夾內容到…", state="normal")
            self.context_menu.entryconfig("轉移已選取項目到…", state="disabled")
            self.context_menu.entryconfig("轉移並建立新資料夾…", state="disabled")
            self.context_menu.entryconfig("重新命名與添加序號…", state="disabled")
            self.context_menu.entryconfig("刪除選取的檔案或資料夾…", state="disabled")
            self.context_menu.entryconfig("刪除資料夾", state="normal")
        else:
            self._context_target = None
            return
        self.context_menu.post(event.x_root, event.y_root)

    def show_context_menu_for_entry(self, event, entry: SubfolderEntry) -> None:
        entry_key = self._item_key_for_entry(entry)
        if entry_key not in self.selected_entry_keys:
            self.selected_entry_keys = {entry_key}
            self.selected_media_paths.clear()
            self._refresh_preview_selection_styles()
        self._context_target = entry
        self._context_media_item = None
        self.context_menu.entryconfig("新增資料夾…", state="normal")
        self.context_menu.entryconfig("添加標籤", state="normal")
        self.context_menu.entryconfig("打開目標資料夾", state="normal")
        self.context_menu.entryconfig("重新命名資料夾", state="normal")
        self.context_menu.entryconfig("重新命名檔案", state="disabled")
        self.context_menu.entryconfig("轉移資料夾內容到…", state="normal")
        self.context_menu.entryconfig("轉移已選取項目到…", state="normal")
        self.context_menu.entryconfig("轉移並建立新資料夾…", state="normal")
        self.context_menu.entryconfig("重新命名與添加序號…", state="normal")
        self.context_menu.entryconfig("刪除選取的檔案或資料夾…", state="normal")
        self.context_menu.entryconfig("刪除資料夾", state="normal")
        self.context_menu.post(event.x_root, event.y_root)

    def show_context_menu_for_media(self, event, item: MediaItem) -> None:
        media_key = self._item_key_for_media(item)
        if media_key not in self.selected_media_paths:
            self.selected_media_paths = {media_key}
            self.selected_entry_keys.clear()
            self._refresh_preview_selection_styles()
        self._context_target = self.current_subfolder_entry
        self._context_media_item = item
        self.context_menu.entryconfig("新增資料夾…", state="disabled")
        self.context_menu.entryconfig("添加標籤", state="disabled")
        self.context_menu.entryconfig("打開目標資料夾", state="normal")
        self.context_menu.entryconfig("重新命名資料夾", state="disabled")
        self.context_menu.entryconfig("重新命名檔案", state="normal")
        self.context_menu.entryconfig("轉移資料夾內容到…", state="disabled")
        self.context_menu.entryconfig("轉移已選取項目到…", state="normal")
        self.context_menu.entryconfig("轉移並建立新資料夾…", state="normal")
        self.context_menu.entryconfig("重新命名與添加序號…", state="normal")
        self.context_menu.entryconfig("刪除選取的檔案或資料夾…", state="normal")
        self.context_menu.entryconfig("刪除資料夾", state="disabled")
        self.context_menu.post(event.x_root, event.y_root)

    def add_tags_to_current_target(self) -> None:
        entry = self._context_target
        if not entry or not entry.relative_key:
            messagebox.showwarning("警告", "請在人物子資料夾上使用此功能")
            return
        dialog = ctk.CTkInputDialog(text="請輸入標籤（逗號分隔）", title="添加標籤")
        raw = dialog.get_input()
        if raw is None:
            return
        tags = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
        if not tags:
            messagebox.showwarning("警告", "沒有可加入的標籤")
            return
        merged = self.tag_repo.add_tags(entry.relative_key, tags)
        media_snap = self._snapshot_media_view()
        self.refresh_tree(restore_state=self._capture_tree_state())
        self._restore_media_view_if_needed(media_snap)
        self.set_status(f"已更新標籤：{entry.subfolder_name} -> {', '.join(merged)}")

    def create_folder_under_current_target(self) -> None:
        entry = self._context_target
        if not entry:
            messagebox.showwarning("警告", "請先在左側樹狀圖選擇一個資料夾層級。")
            return
        parent_folder = Path(entry.subfolder_path).resolve()
        if not parent_folder.is_dir():
            messagebox.showerror("錯誤", "目標層級不存在或不是資料夾。")
            return

        new_name = simpledialog.askstring(
            "新增資料夾",
            f"要在「{parent_folder.name}」底下建立的新資料夾名稱：",
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not self._is_valid_folder_basename(new_name):
            messagebox.showwarning("警告", "名稱無效：不可為空，且不可包含 \\ / : * ? \" < > | 等字元。")
            return

        new_path = parent_folder / new_name
        if new_path.exists():
            messagebox.showerror("錯誤", f"已存在同名項目：{new_name}")
            return
        try:
            new_path.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            messagebox.showerror("新增失敗", str(exc))
            return

        self.store.invalidate_folder_cache(parent_folder)
        self.store.invalidate_folder_cache(new_path)
        tree_state = self._capture_tree_state()
        tree_state["selected_path"] = self._path_key(new_path)
        self.refresh_tree(restore_state=tree_state)
        self.set_status(f"已新增資料夾：{new_path}")

    def open_current_target_folder(self) -> None:
        entry = self._context_target
        if not entry:
            return
        try:
            self.store.open_folder(entry.subfolder_path)
            self.set_status(f"已打開資料夾：{entry.subfolder_path}")
        except Exception as exc:
            messagebox.showerror("錯誤", f"無法打開資料夾：\n{exc}")

    def rename_current_target_folder(self) -> None:
        if self._context_media_item is not None:
            return
        entry = self._context_target
        if not entry:
            return
        root = self.store.ensure_root_folder()
        folder = Path(entry.subfolder_path).resolve()
        try:
            folder.relative_to(Path(root).resolve())
        except ValueError:
            messagebox.showerror("錯誤", "只能重新命名主資料夾底下的項目。")
            return
        if not folder.is_dir():
            messagebox.showerror("錯誤", "目標不是資料夾。")
            return
        if folder == Path(root).resolve():
            messagebox.showwarning("警告", "不可重新命名主資料夾。")
            return

        old_name = folder.name
        new_name = simpledialog.askstring(
            "重新命名資料夾",
            f"新資料夾名稱（目前：{old_name}）",
            initialvalue=old_name,
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        if not self._is_valid_folder_basename(new_name):
            messagebox.showwarning("警告", "名稱無效：不可為空，且不可包含 \\ / : * ? \" < > | 等字元。")
            return
        new_path = folder.parent / new_name
        if new_path.exists():
            messagebox.showerror("錯誤", "已存在相同名稱的項目。")
            return

        try:
            old_rel = self.store.to_relative_key(folder)
        except Exception:
            old_rel = ""
        try:
            folder.rename(new_path)
        except OSError as exc:
            messagebox.showerror("重新命名失敗", str(exc))
            return

        try:
            new_rel = self.store.to_relative_key(new_path)
        except Exception:
            new_rel = ""
        if old_rel and new_rel:
            self.tag_repo.rename_relative_path_root(old_rel, new_rel)
        self._rewrite_tree_order_after_rename(folder, new_path)

        self.store.clear_cache()
        media_snap = self._snapshot_media_view()
        was_same_media_folder = (
            media_snap is not None and Path(media_snap.subfolder_path).resolve() == folder
        )
        tree_state = self._tree_state_after_folder_rename(folder, new_path, self._capture_tree_state())
        self.refresh_tree(restore_state=tree_state)
        root_res = Path(root).resolve()
        if was_same_media_folder and media_snap is not None:
            person_name = new_path.name if new_path.parent == root_res else media_snap.person_name
            self.render_subfolder_media(self._build_entry_for_folder(new_path, person_name))
        elif media_snap is not None:
            try:
                old_r = folder.resolve()
                view_r = Path(media_snap.subfolder_path).resolve()
                rel = view_r.relative_to(old_r)
                np = new_path / rel
                if np.is_dir():
                    if old_r.parent == root_res:
                        person_name = new_path.name
                    else:
                        person_name = media_snap.person_name
                    self.render_subfolder_media(self._build_entry_for_folder(np, person_name))
                else:
                    self._restore_media_view_if_needed(media_snap)
            except ValueError:
                self._restore_media_view_if_needed(media_snap)
        else:
            self._restore_media_view_if_needed(media_snap)
        self.set_status(f"已重新命名資料夾：{old_name} → {new_name}")

    def rename_current_target_file(self) -> None:
        item = self._context_media_item
        if item is None:
            return
        path = Path(item.media_path).resolve()
        if not path.is_file():
            messagebox.showerror("錯誤", "找不到此檔案。")
            return
        suffix = path.suffix
        old_stem = path.stem
        new_stem = simpledialog.askstring(
            "重新命名檔案",
            f"新主檔名（副檔名將維持為 {suffix or '（無）'}）",
            initialvalue=old_stem,
            parent=self.root,
        )
        if new_stem is None:
            return
        new_stem = new_stem.strip()
        if not self._is_valid_file_stem(new_stem):
            messagebox.showwarning("警告", "主檔名無效：不可為空，且不可包含 \\ / : * ? \" < > | 等字元。")
            return
        new_path = path.parent / (new_stem + suffix)
        if new_path.resolve() == path:
            return
        if new_path.exists():
            messagebox.showerror("錯誤", "已存在同名檔案。")
            return
        try:
            path.rename(new_path)
        except OSError as exc:
            messagebox.showerror("重新命名失敗", str(exc))
            return
        self.store.invalidate_folder_cache(path.parent)
        cur = self.current_subfolder_entry
        if cur is not None and self.current_view_mode == "media":
            self.render_subfolder_media(cur)
        self.set_status(f"已重新命名檔案：{path.name} → {new_path.name}")

    @staticmethod
    def _unique_temp_path_for_batch(original: Path) -> Path:
        token = uuid.uuid4().hex[:8]
        return original.with_name(f"{original.name}.tmp_batch_{token}")

    def _ask_rename_title_and_start(
        self, title_validator, *, title_hint: str = "命名規則（例如：ABC）"
    ) -> Optional[tuple[str, int]]:
        base = simpledialog.askstring("重新命名與添加序號", title_hint, parent=self.root)
        if base is None:
            return None
        base = base.strip()
        if not title_validator(base):
            messagebox.showwarning("警告", "命名規則無效：不可為空，且不可包含 \\ / : * ? \" < > | 等字元。")
            return None

        start_raw = simpledialog.askstring("重新命名與添加序號", "起始序號（整數）", parent=self.root)
        if start_raw is None:
            return None
        start_raw = start_raw.strip()
        if not start_raw:
            messagebox.showwarning("警告", "請輸入起始序號。")
            return None
        try:
            start_no = int(start_raw)
        except ValueError:
            messagebox.showwarning("警告", "起始序號必須是整數。")
            return None
        if start_no < 0:
            messagebox.showwarning("警告", "起始序號不可小於 0。")
            return None
        return base, start_no

    def _build_numbered_plan_with_defer_prompt(
        self,
        old_paths: list[Path],
        base: str,
        start_no: int,
        *,
        is_folder: bool,
    ) -> Optional[list[tuple[Path, Path]]]:
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
                candidate = (old.parent / f"{base}_{counter}{suffix}").resolve()
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

    def rename_and_number_selected(self) -> None:
        if self.current_view_mode == "media":
            selected = [m for m in self.current_media_items if self._item_key_for_media(m) in self.selected_media_paths]
            if not selected and self._context_media_item is not None:
                selected = [self._context_media_item]
            if not selected:
                messagebox.showinfo("提示", "請先在預覽區選取要重新命名的檔案。")
                return
            params = self._ask_rename_title_and_start(self._is_valid_file_stem)
            if params is None:
                return
            base, start_no = params
            old_paths = [Path(x.media_path).resolve() for x in selected]
            for old in old_paths:
                if not old.is_file():
                    messagebox.showerror("錯誤", f"找不到檔案：\n{old}")
                    return
            plan = self._build_numbered_plan_with_defer_prompt(old_paths, base, start_no, is_folder=False)
            if plan is None:
                return
            tmp_plan: list[tuple[Path, Path, Path]] = []
            try:
                for old, new in plan:
                    if old == new:
                        continue
                    tmp = self._unique_temp_path_for_batch(old)
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
                messagebox.showerror("重新命名失敗", str(exc))
                return
            touched = {Path(x.media_path).resolve().parent for x in selected}
            for p in touched:
                self.store.invalidate_folder_cache(p)
            cur = self.current_subfolder_entry
            if cur is not None and self.current_view_mode == "media":
                self.render_subfolder_media(cur)
            self.set_status(f"已依排序重新命名 {len(selected)} 個檔案")
            return

        selected_entries = [e for e in self.current_entries if self._item_key_for_entry(e) in self.selected_entry_keys]
        if not selected_entries and self._context_target is not None:
            selected_entries = [self._context_target]
        if not selected_entries:
            messagebox.showinfo("提示", "請先在預覽區選取要重新命名的資料夾。")
            return
        params = self._ask_rename_title_and_start(self._is_valid_folder_basename)
        if params is None:
            return
        base, start_no = params
        old_paths = [Path(x.subfolder_path).resolve() for x in selected_entries]
        for old in old_paths:
            if not old.is_dir():
                messagebox.showerror("錯誤", f"找不到資料夾：\n{old}")
                return
        plan = self._build_numbered_plan_with_defer_prompt(old_paths, base, start_no, is_folder=True)
        if plan is None:
            return
        old_new_rel_pairs: list[tuple[str, str]] = []
        tmp_plan: list[tuple[Path, Path, Path]] = []
        try:
            for old, new in plan:
                if old == new:
                    continue
                try:
                    old_rel = self.store.to_relative_key(old)
                    new_rel = self.store.to_relative_key(new)
                    old_new_rel_pairs.append((old_rel, new_rel))
                except Exception:
                    pass
                tmp = self._unique_temp_path_for_batch(old)
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
            messagebox.showerror("重新命名失敗", str(exc))
            return
        for old_rel, new_rel in old_new_rel_pairs:
            if old_rel and new_rel:
                self.tag_repo.rename_relative_path_root(old_rel, new_rel)
        self.store.clear_cache()
        self.refresh_tree(restore_state=self._capture_tree_state())
        self.set_status(f"已依排序重新命名 {len(selected_entries)} 個資料夾")

    def transfer_current_target_folder(self) -> None:
        entry = self._context_target
        if not entry:
            return
        source_folder = entry.subfolder_path
        target_selected = filedialog.askdirectory(title="選擇目標資料夾", initialdir=str(source_folder.parent))
        if not target_selected:
            return
        target_folder = Path(target_selected).resolve()
        if not messagebox.askyesno(
            "確認轉移",
            f"將「{source_folder.name}」內容搬移到「{target_folder.name}」後，\n會刪除來源資料夾。是否繼續？",
        ):
            return
        try:
            moved_count, renamed_count, source_deleted = self.store.move_folder_content_and_remove_source(
                source_folder, target_folder
            )
        except Exception as exc:
            messagebox.showerror("轉移失敗", str(exc))
            return
        if entry.relative_key:
            source_tags = self.tag_repo.get_tags(entry.relative_key)
            self.tag_repo.remove_key(entry.relative_key)
            try:
                target_key = self.store.to_relative_key(target_folder)
            except Exception:
                target_key = ""
            if source_tags and target_key:
                self.tag_repo.set_tags(target_key, self.tag_repo.get_tags(target_key) + source_tags)
        tree_state = self._capture_tree_state()
        if tree_state.get("selected_path") == self._path_key(source_folder):
            tree_state["selected_path"] = self._path_key(target_folder)
        self.refresh_tree(restore_state=tree_state)
        if source_deleted:
            summary = f"完成歸檔：搬移 {moved_count} 項，衝突改名 {renamed_count} 項，並刪除來源資料夾"
        else:
            summary = (
                f"完成轉移：搬移 {moved_count} 項，衝突改名 {renamed_count} 項；"
                "來源含子資料夾，已保留來源資料夾"
            )
        self.set_status(summary)

    @staticmethod
    def _build_non_conflict_file_path(folder: Path, base_name: str) -> Path:
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

    def transfer_selected_preview_items(self) -> None:
        if self.current_view_mode == "media":
            selected = [m for m in self.current_media_items if self._item_key_for_media(m) in self.selected_media_paths]
            if not selected and self._context_media_item is not None:
                selected = [self._context_media_item]
            if not selected:
                messagebox.showinfo("提示", "請先在預覽區選取至少一個檔案。")
                return
            initial_dir = str(selected[0].media_path.parent)
            target_selected = filedialog.askdirectory(title="選擇目標資料夾", initialdir=initial_dir)
            if not target_selected:
                return
            target_folder = Path(target_selected).resolve()
            if not target_folder.is_dir():
                messagebox.showerror("錯誤", "目標資料夾不存在。")
                return
            if not messagebox.askyesno(
                "確認批次轉移",
                f"確定將 {len(selected)} 個檔案移動到「{target_folder.name}」？",
            ):
                return
            moved_count = 0
            renamed_count = 0
            skipped_same_folder = 0
            failed_count = 0
            touched_parents: set[Path] = set()
            for item in selected:
                src = Path(item.media_path).resolve()
                if not src.is_file():
                    failed_count += 1
                    continue
                if src.parent == target_folder:
                    skipped_same_folder += 1
                    continue
                dst = target_folder / src.name
                if dst.exists():
                    dst = self._build_non_conflict_file_path(target_folder, src.name)
                    renamed_count += 1
                try:
                    shutil.move(str(src), str(dst))
                    moved_count += 1
                    touched_parents.add(src.parent)
                except Exception:
                    failed_count += 1
            for parent in touched_parents:
                self.store.invalidate_folder_cache(parent)
            self.store.invalidate_folder_cache(target_folder)
            cur = self.current_subfolder_entry
            if cur is not None and self.current_view_mode == "media":
                self.render_subfolder_media(cur)
            self.set_status(
                f"批次轉移完成：移動 {moved_count}，改名 {renamed_count}，略過 {skipped_same_folder}，失敗 {failed_count}"
            )
            return

        selected_entries = [e for e in self.current_entries if self._item_key_for_entry(e) in self.selected_entry_keys]
        if not selected_entries and self._context_target is not None:
            selected_entries = [self._context_target]
        if not selected_entries:
            messagebox.showinfo("提示", "請先在預覽區選取至少一個資料夾。")
            return
        initial_dir = str(Path(selected_entries[0].subfolder_path).parent)
        target_selected = filedialog.askdirectory(title="選擇目標資料夾", initialdir=initial_dir)
        if not target_selected:
            return
        target_folder = Path(target_selected).resolve()
        if not messagebox.askyesno(
            "確認批次轉移",
            f"確定將 {len(selected_entries)} 個資料夾的內容搬移到「{target_folder.name}」？\n"
            "來源資料夾若無子資料夾，會在搬移後刪除。",
        ):
            return
        moved_count = 0
        renamed_count = 0
        deleted_count = 0
        failed_count = 0
        for entry in selected_entries:
            source_folder = Path(entry.subfolder_path).resolve()
            try:
                moved, renamed, source_deleted = self.store.move_folder_content_and_remove_source(source_folder, target_folder)
                moved_count += moved
                renamed_count += renamed
                if source_deleted:
                    deleted_count += 1
            except Exception:
                failed_count += 1
                continue
            if entry.relative_key:
                source_tags = self.tag_repo.get_tags(entry.relative_key)
                self.tag_repo.remove_key(entry.relative_key)
                try:
                    target_key = self.store.to_relative_key(target_folder)
                except Exception:
                    target_key = ""
                if source_tags and target_key:
                    self.tag_repo.set_tags(target_key, self.tag_repo.get_tags(target_key) + source_tags)
        self.refresh_tree(restore_state=self._capture_tree_state())
        self.set_status(
            f"批次轉移完成：搬移 {moved_count}，改名 {renamed_count}，刪除來源 {deleted_count}，失敗 {failed_count}"
        )

    def delete_current_target_folder(self) -> None:
        entry = self._context_target
        if not entry:
            return

        folder = entry.subfolder_path
        if self.store.root_folder and Path(folder).resolve() == Path(self.store.root_folder).resolve():
            messagebox.showwarning("警告", "不可刪除主資料夾")
            return

        if not messagebox.askyesno(
            "確認刪除",
            f"確定要刪除資料夾「{folder.name}」及其所有內容嗎？\n\n此操作無法復原。",
        ):
            return

        folder_path = Path(folder).resolve()
        try:
            file_count = self.store.delete_folder(folder)
        except Exception as exc:
            messagebox.showerror("刪除失敗", str(exc))
            return

        try:
            relative_prefix = self.store.to_relative_key(folder_path)
        except Exception:
            relative_prefix = ""
        if relative_prefix:
            self.tag_repo.remove_keys_by_prefix(relative_prefix)
        self._tree_order_after_delete_folder(folder_path)

        tree_state = self._prune_tree_state_after_deleted_paths(self._capture_tree_state(), [folder_path])
        self.refresh_tree(restore_state=tree_state)
        self.set_status(f"已刪除資料夾：{folder.name}（移除 {file_count} 個檔案）")

    def import_tags_json(self) -> None:
        selected = filedialog.askopenfilename(title="匯入標籤 JSON", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not selected:
            return
        try:
            self.tag_repo.import_json(Path(selected), merge=True)
            media_snap = self._snapshot_media_view()
            self.refresh_tree(restore_state=self._capture_tree_state())
            self._restore_media_view_if_needed(media_snap)
            self.set_status("已匯入 JSON 標籤")
        except Exception as exc:
            messagebox.showerror("匯入失敗", str(exc))

    def import_tags_csv(self) -> None:
        selected = filedialog.askopenfilename(title="匯入標籤 CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not selected:
            return
        try:
            self.tag_repo.import_csv(Path(selected), merge=True)
            media_snap = self._snapshot_media_view()
            self.refresh_tree(restore_state=self._capture_tree_state())
            self._restore_media_view_if_needed(media_snap)
            self.set_status("已匯入 CSV 標籤")
        except Exception as exc:
            messagebox.showerror("匯入失敗", str(exc))

    def export_tags_json(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="匯出標籤 JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            self.tag_repo.export_json(Path(selected))
            self.set_status("已匯出 JSON 標籤")
        except Exception as exc:
            messagebox.showerror("匯出失敗", str(exc))

    def export_tags_csv(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="匯出標籤 CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            self.tag_repo.export_csv(Path(selected))
            self.set_status("已匯出 CSV 標籤")
        except Exception as exc:
            messagebox.showerror("匯出失敗", str(exc))

    def on_close(self) -> None:
        self.scan_executor.shutdown(wait=False, cancel_futures=True)
        self.thumb_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


class MediaBrowserWindow:
    """雙擊預覽後的大畫面瀏覽：圖片內嵌、←／→ 循環切換；影片顯示預覽格並可開啟系統播放器。"""

    _LOAD_IMAGE_MAX = (8192, 8192)
    _VIDEO_STILL_SIZE = (1920, 1080)

    def __init__(self, app: PeopleFolderManagerApp, items: list[MediaItem], start_index: int) -> None:
        self.app = app
        self.items = list(items)
        self.index = max(0, min(start_index, len(self.items) - 1)) if self.items else 0
        self._load_gen = 0
        self._resize_after: Optional[str] = None
        self._source_rgb: Optional[Image.Image] = None
        self._photo_image: Optional[ImageTk.PhotoImage] = None

        self.top = ctk.CTkToplevel(app.root)
        self.top.title("媒體瀏覽")
        self.top.configure(fg_color=app.ui_colors["bg"])
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<Escape>", lambda _e: self.close())
        self.top.bind("<Left>", lambda _e: self._prev())
        self.top.bind("<Right>", lambda _e: self._next())
        self.top.bind("<Return>", lambda _e: self._open_external())
        self.top.bind("<KP_Left>", lambda _e: self._prev())
        self.top.bind("<KP_Right>", lambda _e: self._next())

        toolbar = ctk.CTkFrame(self.top, fg_color="transparent")
        toolbar.pack(fill="x", padx=12, pady=(10, 6))
        self.title_label = ctk.CTkLabel(
            toolbar, text="", anchor="w", font=app.font_title, text_color=app.ui_colors["text"]
        )
        self.title_label.pack(side="left", fill="x", expand=True)

        btn_fr = ctk.CTkFrame(toolbar, fg_color="transparent")
        btn_fr.pack(side="right")
        ctk.CTkButton(btn_fr, text="‹ 上一張", width=88, command=self._prev, font=app.font_small).pack(side="left", padx=4)
        ctk.CTkButton(btn_fr, text="下一張 ›", width=88, command=self._next, font=app.font_small).pack(side="left", padx=4)
        ctk.CTkButton(btn_fr, text="以程式開啟", width=100, command=self._open_external, font=app.font_small).pack(
            side="left", padx=4
        )
        ctk.CTkButton(
            btn_fr,
            text="關閉",
            width=72,
            fg_color=app.ui_colors["border"],
            hover_color="#cbd5e1",
            text_color=app.ui_colors["text"],
            command=self.close,
            font=app.font_small,
        ).pack(
            side="left", padx=(12, 0)
        )

        self.hint_label = ctk.CTkLabel(
            self.top,
            text="← → 循環切換同清單　Enter 以系統預設程式開啟目前檔案　Esc 關閉",
            text_color=app.ui_colors["muted"],
            font=app.font_small,
        )
        self.hint_label.pack(fill="x", padx=12, pady=(0, 6))

        self.canvas = tk.Canvas(self.top, bg=app.ui_colors["panel"], highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._try_maximize()
        self._show_current()
        self.top.after(50, self._grab_modal)

    def _grab_modal(self) -> None:
        try:
            self.top.focus_force()
            self.top.grab_set()
        except tk.TclError:
            pass

    def _try_maximize(self) -> None:
        self.top.update_idletasks()
        try:
            self.top.state("zoomed")
        except tk.TclError:
            try:
                self.top.attributes("-zoomed", True)
            except tk.TclError:
                try:
                    self.top.wm_state("zoomed")
                except tk.TclError:
                    pass

    def close(self) -> None:
        if self._resize_after is not None:
            try:
                self.top.after_cancel(self._resize_after)
            except Exception:
                pass
            self._resize_after = None
        try:
            self.top.grab_release()
        except Exception:
            pass
        try:
            self.top.destroy()
        except Exception:
            pass
        if getattr(self.app, "_active_media_browser", None) is self:
            self.app._active_media_browser = None

    def _on_canvas_configure(self, event: tk.Event) -> None:
        if event.widget != self.canvas:
            return
        if self._resize_after is not None:
            try:
                self.top.after_cancel(self._resize_after)
            except Exception:
                pass
        self._resize_after = self.top.after(120, self._render_canvas_from_source)

    @staticmethod
    def _scale_pil_to_fit(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            return img
        scale = min(max_w / iw, max_h / ih, 1.0)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        if nw == iw and nh == ih:
            return img
        return img.resize((nw, nh), Image.Resampling.LANCZOS)

    def _render_canvas_from_source(self) -> None:
        self._resize_after = None
        if self._source_rgb is None:
            return
        try:
            if not self.top.winfo_exists():
                return
        except tk.TclError:
            return
        self.canvas.update_idletasks()
        cw = max(200, self.canvas.winfo_width())
        ch = max(200, self.canvas.winfo_height())
        scaled = self._scale_pil_to_fit(self._source_rgb, cw, ch)
        try:
            self._photo_image = ImageTk.PhotoImage(scaled, master=self.canvas)
        except Exception:
            return
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo_image, anchor="center")

    def _prev(self) -> None:
        if len(self.items) <= 1:
            return
        self.index = (self.index - 1) % len(self.items)
        self._show_current()

    def _next(self) -> None:
        if len(self.items) <= 1:
            return
        self.index = (self.index + 1) % len(self.items)
        self._show_current()

    def _open_external(self) -> None:
        if not self.items:
            return
        self.app._open_path_in_default_app(self.items[self.index].media_path)

    def _show_current(self) -> None:
        if not self.items:
            return
        item = self.items[self.index]
        self.top.title(f"媒體瀏覽 — {item.media_path.name}")
        n = len(self.items)
        kind = "圖片" if item.media_type == "image" else "影片"
        self.title_label.configure(text=f"{item.media_path.name}　（{self.index + 1} / {n}）　{kind}")
        self._load_gen += 1
        gen = self._load_gen
        self._source_rgb = None
        self.canvas.delete("all")
        cw = max(400, self.canvas.winfo_width())
        ch = max(300, self.canvas.winfo_height())
        self.canvas.create_text(
            cw // 2,
            ch // 2,
            text="載入中…",
            fill=self.app.ui_colors["muted"],
            font=(self.app._platform_font_family(), 16),
        )

        fut = self.app.thumb_executor.submit(self._load_item_pil_worker, item, self.app.thumbnail_service)
        fut.add_done_callback(
            lambda f, g=gen: self.app._enqueue_ui_task(self._apply_loaded_pil, g, f)
        )

    @staticmethod
    def _load_item_pil_worker(item: MediaItem, thumbnail_service: ThumbnailService) -> Image.Image:
        if item.media_type == "image":
            try:
                with Image.open(item.media_path) as im:
                    rgb = im.convert("RGB")
                    rgb.thumbnail(MediaBrowserWindow._LOAD_IMAGE_MAX, Image.Resampling.LANCZOS)
                    return rgb.copy()
            except Exception:
                return thumbnail_service._build_placeholder("讀取失敗", (640, 480))
        return thumbnail_service.get_file_thumbnail(
            item.media_path, "video", MediaBrowserWindow._VIDEO_STILL_SIZE
        )

    def _apply_loaded_pil(self, gen: int, future) -> None:
        if gen != self._load_gen:
            return
        try:
            if not self.top.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            pil = future.result()
        except Exception:
            pil = self.app.thumbnail_service._build_placeholder("讀取失敗", (640, 480))
        self._source_rgb = pil
        self._render_canvas_from_source()


def main() -> None:
    app = PeopleFolderManagerApp()
    app.run()


if __name__ == "__main__":
    main()
