#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import sys
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import tkinter as tk
from PIL import Image, ImageDraw
from tkinter import filedialog, messagebox, simpledialog, ttk

from app_paths import get_app_data_dir, get_config_path
from people_data_store import MediaItem, PeopleDataStore, SubfolderEntry
from tag_repository import TagRepository

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None


APP_NAME = "PeopleFolderManager"
ENTRY_THUMBNAIL_SIZE = (240, 170)
MEDIA_THUMBNAIL_SIZE = (240, 200)
ENTRY_CARD_SIZE = (280, 260)
MEDIA_CARD_SIZE = (280, 290)

ENTRY_COLUMNS = 3
MEDIA_COLUMNS = 4
ENTRY_BATCH_FIRST = 6
ENTRY_BATCH_SIZE = 12
MEDIA_BATCH_FIRST = 8
MEDIA_BATCH_SIZE = 16
THUMB_YVIEW_LOAD_THRESHOLD = 0.78
THUMB_YVIEW_DEBOUNCE_MS = 90

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


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
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
        try:
            value = float((result.stdout or "").strip())
        except Exception:
            return None
        return value if value > 0 else None

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
        canvas = Image.new("RGB", size, "#1f1f1f")
        copy = image.copy()
        copy.thumbnail(size, Image.Resampling.LANCZOS)
        x = (size[0] - copy.width) // 2
        y = (size[1] - copy.height) // 2
        canvas.paste(copy, (x, y))
        return canvas

    def _build_placeholder(self, text: str, size: tuple[int, int]) -> Image.Image:
        image = Image.new("RGB", size, "#2b2b2b")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline="#555555", width=1)
        draw.text((14, size[1] // 2 - 6), text, fill="#b5b5b5")
        return image


class PeopleFolderManagerApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("人物資料夾管理器")
        self.root.geometry("1450x920")

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
        self.current_view_mode = "entries"
        self._thumb_paging_state: Optional[dict] = None
        self._thumb_scroll_hooked = False
        self._thumb_yview_after_id: Optional[str] = None
        self.current_subfolder_entry: Optional[SubfolderEntry] = None
        self.filter_vars: dict[str, ctk.BooleanVar] = {}
        self.selected_filter_tags: set[str] = set()
        self.filter_media_video_var = ctk.BooleanVar(value=False)
        self.filter_media_image_var = ctk.BooleanVar(value=False)
        self._context_target: Optional[SubfolderEntry] = None
        self._context_media_item: Optional[MediaItem] = None

        self.load_session_id = 0
        self.active_session_id = 0
        self.session_first_thumb_logged: dict[int, bool] = {}
        self.profile_enabled = True
        self.selection_debounce_ms = 120
        self._pending_select_after_id: Optional[str] = None
        self._pending_selected_item: Optional[str] = None
        self._ui_task_queue: queue.Queue = queue.Queue()
        self._ui_pump_pending = False

        self._build_layout()
        self._apply_saved_root()
        self.refresh_tree()
        self.refresh_filter_panel()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _load_config(self) -> dict:
        default = {"root_folder": ""}
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
        top_frame = ctk.CTkFrame(self.root)
        top_frame.pack(fill="x", padx=10, pady=(10, 6))

        ctk.CTkLabel(top_frame, text="主資料夾：", font=("Arial", 12, "bold")).pack(side="left", padx=(10, 4))
        self.root_dir_var = ctk.StringVar(value="")
        self.root_dir_entry = ctk.CTkEntry(top_frame, textvariable=self.root_dir_var, width=620)
        self.root_dir_entry.pack(side="left", padx=4, pady=8)
        ctk.CTkButton(top_frame, text="選擇資料夾", width=100, command=self.choose_root_folder).pack(side="left", padx=4)
        ctk.CTkButton(top_frame, text="刷新", width=70, command=self.refresh_tree).pack(side="left", padx=4)
        ctk.CTkButton(top_frame, text="匯入 JSON", width=90, command=self.import_tags_json).pack(side="left", padx=(14, 4))
        ctk.CTkButton(top_frame, text="匯入 CSV", width=90, command=self.import_tags_csv).pack(side="left", padx=4)
        ctk.CTkButton(top_frame, text="匯出 JSON", width=90, command=self.export_tags_json).pack(side="left", padx=(14, 4))
        ctk.CTkButton(top_frame, text="匯出 CSV", width=90, command=self.export_tags_csv).pack(side="left", padx=4)

        body = ctk.CTkFrame(self.root)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        left_frame = ctk.CTkFrame(body)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)
        ctk.CTkLabel(left_frame, text="導覽樹狀欄位", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=(10, 6))

        tree_host = tk.Frame(left_frame, bg="#2b2b2b")
        tree_host.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)

        self.folder_tree = ttk.Treeview(tree_host, show="tree", selectmode="browse")
        self.folder_tree.grid(row=0, column=0, sticky="nsew")
        tree_vsb = ttk.Scrollbar(tree_host, orient="vertical", command=self.folder_tree.yview)
        tree_vsb.grid(row=0, column=1, sticky="ns")
        self.folder_tree.configure(yscrollcommand=tree_vsb.set)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", borderwidth=0)
        style.configure("Treeview.Heading", background="#1f1f1f", foreground="white")
        style.map("Treeview", background=[("selected", "#144870")])

        self.folder_tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.folder_tree.bind("<<TreeviewOpen>>", self.on_tree_open)
        self._bind_right_click_menu(self.folder_tree, self.on_tree_right_click)

        right_frame = ctk.CTkFrame(body)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)
        right_frame.grid_rowconfigure(2, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        self.scope_label = ctk.CTkLabel(right_frame, text="目前檢視：未選擇", anchor="w", font=("Arial", 12, "bold"))
        self.scope_label.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        filter_frame = ctk.CTkFrame(right_frame)
        filter_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        ctk.CTkLabel(filter_frame, text="標籤篩選（勾選即套用 OR）", font=("Arial", 11, "bold")).pack(
            anchor="w", padx=10, pady=(8, 4)
        )
        self.filter_tags_container = ctk.CTkScrollableFrame(filter_frame, height=96)
        self.filter_tags_container.pack(fill="x", padx=8, pady=(0, 6))
        media_row = ctk.CTkFrame(filter_frame, fg_color="transparent")
        media_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(media_row, text="媒體類型：", font=("Arial", 11, "bold")).pack(side="left", padx=(0, 6))
        ctk.CTkCheckBox(
            media_row,
            text="影片",
            variable=self.filter_media_video_var,
            command=self.on_media_type_filter_changed,
            width=70,
        ).pack(side="left", padx=(0, 10))
        ctk.CTkCheckBox(
            media_row,
            text="圖片",
            variable=self.filter_media_image_var,
            command=self.on_media_type_filter_changed,
            width=70,
        ).pack(side="left")

        self.thumbnail_scroll = ctk.CTkScrollableFrame(right_frame, label_text="子資料夾縮圖預覽")
        self.thumbnail_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._ensure_thumbnail_scroll_hook()

        status_frame = ctk.CTkFrame(self.root)
        status_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.status_label = ctk.CTkLabel(status_frame, text="就緒", anchor="w")
        self.status_label.pack(side="left", padx=10, pady=6)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="添加標籤", command=self.add_tags_to_current_target)
        self.context_menu.add_command(label="打開目標資料夾", command=self.open_current_target_folder)
        self.context_menu.add_command(label="重新命名資料夾", command=self.rename_current_target_folder)
        self.context_menu.add_command(label="重新命名檔案", command=self.rename_current_target_file)
        self.context_menu.add_command(label="轉移資料夾內容到…", command=self.transfer_current_target_folder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="刪除資料夾", command=self.delete_current_target_folder)

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
        self.person_entries.clear()
        self.current_entries = []
        self.current_media_items = []
        self.current_view_mode = "entries"
        self.current_subfolder_entry = None
        self.scope_label.configure(text="目前檢視：未選擇")

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
            for person_folder in self.store.get_people_folders():
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
            extra=f"people={len(self.store.get_people_folders()) if self.store.root_folder else 0}",
        )

    def _populate_person_tree_shallow(self, person_node: str, person_folder: Path) -> None:
        """僅列出第一層子資料夾名稱，不掃描媒體（延遲到選取人物／根節點時再掃描）。"""
        for subfolder in self.store.get_subfolders(person_folder):
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

    def _tree_folder_visible_with_media_filter(self, folder: Path) -> bool:
        if not self._media_type_filter_enabled():
            return True
        if self._folder_matches_media_type_filter(folder):
            return True
        try:
            for sub in self.store.get_subfolders(folder):
                if self._tree_folder_visible_with_media_filter(sub):
                    return True
        except Exception:
            pass
        return False

    def _folder_has_visible_subdirs_for_tree(self, folder_path: Path) -> bool:
        if not self._media_type_filter_enabled():
            return self._folder_has_subdirs(folder_path)
        try:
            for sub in self.store.get_subfolders(folder_path):
                if self._tree_folder_visible_with_media_filter(sub):
                    return True
        except Exception:
            return False
        return False

    def _apply_media_entry_filter(self, entries: list[SubfolderEntry]) -> list[SubfolderEntry]:
        if not self._media_type_filter_enabled():
            return entries
        return [e for e in entries if self._tree_folder_visible_with_media_filter(e.subfolder_path)]

    def _filter_media_items_for_preview(self, items: list[MediaItem]) -> list[MediaItem]:
        want_v = self.filter_media_video_var.get()
        want_i = self.filter_media_image_var.get()
        if not want_v and not want_i:
            return list(items)
        if want_v and want_i:
            return list(items)
        if want_v:
            return [m for m in items if m.media_type == "video"]
        return [m for m in items if m.media_type == "image"]

    def _refresh_tree_and_reload_selection(self) -> None:
        tree_state = self._capture_tree_state()
        self.refresh_tree(restore_state=tree_state)
        selected = self.folder_tree.selection()
        if selected:
            self._apply_tree_selection_from_item_id(selected[0])
        else:
            self.clear_thumbnail_cards()
            self.scope_label.configure(text="目前檢視：未選擇")
            self.set_status("就緒")

    def on_media_type_filter_changed(self) -> None:
        self._refresh_tree_and_reload_selection()

    def _collect_tag_filter_state_for_person(
        self, person_folder: Path, person_name: str
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
                        if not self._folder_matches_media_type_filter(path):
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
        for person_folder in self.store.get_people_folders():
            if not self._tree_folder_visible_with_media_filter(person_folder):
                continue
            visible, matching_entries = self._collect_tag_filter_state_for_person(person_folder, person_folder.name)
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
        subfolders = self.store.get_subfolders(parent_path)
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
            card, image_label = self._create_media_card(row, col, item)
            self._bind_media_card_context_menu(card, item)
            fut = self.thumb_executor.submit(
                self.thumbnail_service.get_file_thumbnail, item.media_path, item.media_type, MEDIA_THUMBNAIL_SIZE
            )
            fut.add_done_callback(
                lambda f, session_id=sid, lbl=image_label: self._enqueue_ui_task(
                    self._apply_thumbnail, session_id, lbl, f, MEDIA_THUMBNAIL_SIZE
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
        for person_folder in self.store.get_people_folders():
            entries = self.store.get_subfolder_entries_shallow(person_folder)
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
        self.person_entries[person_folder.name] = entries
        self.render_entries(entries, reuse_session=sid)

    def on_tree_select(self, _event=None) -> None:
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
            if self.selected_filter_tags:
                merged_tf: list[SubfolderEntry] = []
                for entries in self.person_entries.values():
                    merged_tf.extend(entries)
                self.render_entries(merged_tf)
            else:
                people = self.store.get_people_folders()
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
            cached = self.person_entries.get(person_folder.name)
            if cached is not None:
                self.render_entries(cached)
            else:
                self._begin_load_person_entries(person_folder)
        elif node_type == "subfolder":
            entry = self._entry_for_tree_subfolder(payload)
            self.current_scope_label = f"{entry.person_name} / {entry.subfolder_name}"
            self.render_subfolder_media(entry)

    def clear_thumbnail_cards(self) -> None:
        self._cancel_thumb_yview_debounce()
        self._thumb_paging_state = None
        for child in self.thumbnail_scroll.winfo_children():
            child.destroy()

    def render_entries(self, entries: list[SubfolderEntry], *, reuse_session: Optional[int] = None) -> None:
        sid = reuse_session if reuse_session is not None else self._new_session()
        self.current_view_mode = "entries"
        self.current_subfolder_entry = None
        self.current_entries = list(entries)
        self.current_media_items = []
        self.scope_label.configure(text=f"目前檢視：{self.current_scope_label}")
        filtered = self._apply_media_entry_filter(self._apply_tag_filter(entries))
        self.clear_thumbnail_cards()
        if not filtered:
            ctk.CTkLabel(self.thumbnail_scroll, text="沒有可顯示的子資料夾").grid(row=0, column=0, padx=16, pady=16, sticky="w")
            self.set_status("目前標籤／媒體類型篩選下沒有結果")
            return
        for col in range(ENTRY_COLUMNS):
            self.thumbnail_scroll.grid_columnconfigure(col, weight=0, minsize=ENTRY_CARD_SIZE[0] + 16)
        self._ensure_thumbnail_scroll_hook()
        self._thumb_paging_state = {"sid": sid, "kind": "entries", "entries": filtered, "next_index": 0}
        self._thumb_append_entries(self._thumb_paging_state)
        self.root.after(16, self._try_fill_thumbnail_viewport)

    def _create_entry_card(self, row: int, col: int, entry: SubfolderEntry):
        card = ctk.CTkFrame(self.thumbnail_scroll)
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
        ctk.CTkLabel(card, text=title, anchor="w", font=("Arial", 12, "bold"), height=24).grid(row=1, column=0, padx=8, sticky="ew")
        tags_text = ", ".join(self.tag_repo.get_effective_tags(entry.relative_key)) or "（尚未標籤）"
        if len(tags_text) > 30:
            tags_text = tags_text[:30] + "..."
        ctk.CTkLabel(card, text=f"標籤：{tags_text}", anchor="w", height=16).grid(row=2, column=0, padx=8, pady=(0, 1), sticky="ew")
        ctk.CTkLabel(card, text=f"媒體數量：{entry.media_count}", anchor="w", height=20).grid(row=3, column=0, padx=8, pady=(0, 8), sticky="ew")
        return card, image_label

    def render_subfolder_media(self, entry: SubfolderEntry) -> None:
        sid = self._new_session()
        self.current_view_mode = "media"
        self.current_subfolder_entry = entry
        self.current_entries = [entry]
        self.current_scope_label = f"{entry.person_name} / {entry.subfolder_name}"
        self.scope_label.configure(text=f"目前檢視：{self.current_scope_label}（媒體預覽）")
        self.clear_thumbnail_cards()
        self.current_media_items = []
        ctk.CTkLabel(self.thumbnail_scroll, text="載入中...").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        self.set_status("正在掃描子資料夾媒體...")

        start = self._perf_start()
        fut = self.scan_executor.submit(self.store.list_media_items, entry.subfolder_path)
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
            media_items = future.result()
        except Exception as exc:
            messagebox.showerror("錯誤", f"載入媒體清單失敗：\n{exc}")
            return
        display_items = self._filter_media_items_for_preview(media_items)
        self.current_media_items = display_items
        if not media_items:
            ctk.CTkLabel(self.thumbnail_scroll, text="此子資料夾內沒有圖片或影片").grid(
                row=0, column=0, padx=16, pady=16, sticky="w"
            )
            self.set_status("子資料夾內沒有可預覽媒體")
            return
        if not display_items:
            ctk.CTkLabel(self.thumbnail_scroll, text="目前媒體類型篩選下沒有符合的項目").grid(
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
        card = ctk.CTkFrame(self.thumbnail_scroll)
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        card.configure(width=MEDIA_CARD_SIZE[0], height=MEDIA_CARD_SIZE[1])
        card.grid_propagate(False)
        card.grid_rowconfigure(0, weight=0)
        card.grid_rowconfigure(1, weight=0)
        card.grid_rowconfigure(2, weight=0)
        card.grid_columnconfigure(0, weight=1)

        holder = self.thumbnail_service._build_placeholder("LOADING", MEDIA_THUMBNAIL_SIZE)
        image = ctk.CTkImage(light_image=holder, dark_image=holder, size=MEDIA_THUMBNAIL_SIZE)
        image_label = ctk.CTkLabel(card, text="", image=image, width=MEDIA_THUMBNAIL_SIZE[0], height=MEDIA_THUMBNAIL_SIZE[1])
        image_label.image_ref = image
        image_label.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="n")

        short_name = item.media_path.name if len(item.media_path.name) <= 28 else item.media_path.name[:28] + "..."
        ctk.CTkLabel(card, text=short_name, anchor="w").grid(row=1, column=0, padx=8, sticky="ew")
        ctk.CTkLabel(card, text=f"類型：{'圖片' if item.media_type == 'image' else '影片'}", anchor="w", height=20).grid(
            row=2, column=0, padx=8, pady=(2, 8), sticky="ew"
        )
        return card, image_label

    def _bind_media_card_context_menu(self, card: ctk.CTkFrame, item: MediaItem) -> None:
        def handler(event: tk.Event, m: MediaItem = item) -> None:
            self.show_context_menu_for_media(event, m)

        self._bind_right_click_menu(card, handler)
        for child in card.winfo_children():
            self._bind_right_click_menu(child, handler)

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
            ctk.CTkCheckBox(cell, text=tag, variable=var, command=self.on_filter_changed, width=100).pack(
                side="left", padx=(0, 0)
            )
            ctk.CTkButton(
                cell,
                text="×",
                width=24,
                height=22,
                fg_color="#6b2a2a",
                hover_color="#8b3a3a",
                font=("Arial", 14, "bold"),
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
        if node_type == "subfolder":
            self._context_target = self._entry_for_tree_subfolder(payload)
            self.context_menu.entryconfig("添加標籤", state="normal")
            self.context_menu.entryconfig("打開目標資料夾", state="normal")
            self.context_menu.entryconfig("重新命名資料夾", state="normal")
            self.context_menu.entryconfig("重新命名檔案", state="disabled")
            self.context_menu.entryconfig("轉移資料夾內容到…", state="normal")
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
            self.context_menu.entryconfig("添加標籤", state="disabled")
            self.context_menu.entryconfig("打開目標資料夾", state="normal")
            self.context_menu.entryconfig("重新命名資料夾", state="normal")
            self.context_menu.entryconfig("重新命名檔案", state="disabled")
            self.context_menu.entryconfig("轉移資料夾內容到…", state="normal")
            self.context_menu.entryconfig("刪除資料夾", state="normal")
        else:
            self._context_target = None
            return
        self.context_menu.post(event.x_root, event.y_root)

    def show_context_menu_for_entry(self, event, entry: SubfolderEntry) -> None:
        self._context_target = entry
        self._context_media_item = None
        self.context_menu.entryconfig("添加標籤", state="normal")
        self.context_menu.entryconfig("打開目標資料夾", state="normal")
        self.context_menu.entryconfig("重新命名資料夾", state="normal")
        self.context_menu.entryconfig("重新命名檔案", state="disabled")
        self.context_menu.entryconfig("轉移資料夾內容到…", state="normal")
        self.context_menu.entryconfig("刪除資料夾", state="normal")
        self.context_menu.post(event.x_root, event.y_root)

    def show_context_menu_for_media(self, event, item: MediaItem) -> None:
        self._context_target = self.current_subfolder_entry
        self._context_media_item = item
        self.context_menu.entryconfig("添加標籤", state="disabled")
        self.context_menu.entryconfig("打開目標資料夾", state="normal")
        self.context_menu.entryconfig("重新命名資料夾", state="disabled")
        self.context_menu.entryconfig("重新命名檔案", state="normal")
        self.context_menu.entryconfig("轉移資料夾內容到…", state="disabled")
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

        try:
            file_count = self.store.delete_folder(folder)
        except Exception as exc:
            messagebox.showerror("刪除失敗", str(exc))
            return

        prefix = self._path_key(folder)
        try:
            relative_prefix = self.store.to_relative_key(folder)
        except Exception:
            relative_prefix = ""
        if relative_prefix:
            self.tag_repo.remove_keys_by_prefix(relative_prefix)

        tree_state = self._capture_tree_state()
        if tree_state.get("selected_path") == prefix:
            tree_state["selected_path"] = self._path_key(folder.parent)
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


def main() -> None:
    app = PeopleFolderManagerApp()
    app.run()


if __name__ == "__main__":
    main()
