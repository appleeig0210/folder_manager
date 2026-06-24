from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_ctx
from api.schemas import (
    EntryItem,
    MediaItemResponse,
    PreviewEntriesResponse,
    PreviewFolderResponse,
    PreviewMediaResponse,
)
from api.services.thumbnail_service import ThumbnailService
from people_data_store import SubfolderEntry

router = APIRouter(prefix="/api/preview", tags=["preview"])


def _entry_to_item(entry: SubfolderEntry, store) -> EntryItem:
    preview_samples = [
        {"path": str(path.resolve()), "media_type": media_type}
        for path, media_type in store.get_folder_preview_samples(entry.subfolder_path, limit=3)
    ]
    return EntryItem(
        id=str(entry.subfolder_path.resolve()),
        person_name=entry.person_name,
        subfolder_name=entry.subfolder_name,
        path=str(entry.subfolder_path.resolve()),
        relative_key=entry.relative_key,
        preview_path=str(entry.preview_path.resolve()) if entry.preview_path else None,
        preview_type=entry.preview_type,
        media_count=entry.media_count,
        preview_samples=preview_samples,
    )


def _media_to_item(ctx, media_path: Path, media_type: str, tags: list[str]) -> MediaItemResponse:
    duration = None
    duration_label = None
    if media_type == "video":
        duration = ctx.thumbnail_service.get_video_duration_seconds(media_path)
        if duration is not None:
            duration_label = ThumbnailService.format_video_duration(duration)
    return MediaItemResponse(
        id=str(media_path.resolve()),
        path=str(media_path.resolve()),
        name=media_path.name,
        media_type=media_type,
        duration_seconds=duration,
        duration_label=duration_label,
        tags=tags,
    )


def _resolve_person_name(store, folder: Path) -> str:
    root = store.ensure_root_folder().resolve()
    target = folder.resolve()
    if target == root:
        return root.name
    try:
        rel = target.relative_to(root)
        if rel.parts:
            return rel.parts[0]
    except ValueError:
        pass
    return target.parent.name or target.name


def _folder_scope_label(store, folder: Path) -> str:
    root = store.ensure_root_folder().resolve()
    target = folder.resolve()
    if target == root:
        return root.name
    crumbs = []
    current = root
    try:
        rel = target.relative_to(root)
    except ValueError:
        return target.name
    for part in rel.parts:
        current = current / part
        crumbs.append(current.name)
    return " / ".join(crumbs)


def _collect_folder_entries(ctx, folder: Path) -> list[SubfolderEntry]:
    person_name = _resolve_person_name(ctx.store, folder)
    child_order = ctx.config.get("tree_child_order") or {}
    ordered = ctx.tree_service.get_ordered_subfolders(folder, child_order)
    return [ctx.preview_service.build_entry_for_folder(sub, person_name) for sub in ordered]


def _apply_entry_manual_order(ctx, entries: list[SubfolderEntry], scope_path: str) -> list[SubfolderEntry]:
    if ctx.preview_sort_mode != "manual":
        return entries
    order = ctx.manual_entry_order.get(scope_path, [])
    if not order:
        return entries
    return sorted(
        entries,
        key=lambda e: (
            order.index(str(e.subfolder_path.resolve()))
            if str(e.subfolder_path.resolve()) in order
            else 10_000,
            e.subfolder_name.casefold(),
        ),
    )


def _apply_media_manual_order(ctx, display: list, scope_path: str) -> list:
    if ctx.preview_sort_mode != "manual":
        return display
    order = ctx.manual_media_order.get(scope_path, [])
    if not order:
        return display
    return sorted(
        display,
        key=lambda m: (
            order.index(str(m.media_path.resolve()))
            if str(m.media_path.resolve()) in order
            else 10_000,
            m.media_path.name.casefold(),
        ),
    )


@router.get("/folder", response_model=PreviewFolderResponse)
def get_folder(
    path: Optional[str] = Query(default=None),
    paths: list[str] = Query(default=[]),
) -> PreviewFolderResponse:
    ctx = get_ctx()
    if ctx.store.root_folder is None:
        raise HTTPException(status_code=400, detail="請先設定主資料夾")

    raw_paths = paths or ([path] if path else [])
    if not raw_paths:
        raw_paths = [str(ctx.store.root_folder.resolve())]

    folders = [Path(p).resolve() for p in raw_paths if p]
    if not folders:
        raise HTTPException(status_code=400, detail="請提供資料夾路徑")
    for folder in folders:
        if not folder.is_dir():
            raise HTTPException(status_code=400, detail=f"路徑不是資料夾：{folder}")

    ctx.keyword_service.reconcile_scope(folders)

    if len(folders) == 1:
        folder = folders[0]
        scope_path = str(folder)
        scope_label = _folder_scope_label(ctx.store, folder)
        subfolder_entries = _collect_folder_entries(ctx, folder)
        _, media_items = ctx.preview_service.scan_direct_media_for_preview(
            folder,
            ctx.selected_filter_tags,
            ctx.filter_media_video,
            ctx.filter_media_image,
            ctx.filter_duration_min,
            ctx.filter_duration_max,
        )
    else:
        scope_path = "||".join(str(p) for p in folders)
        scope_label = f"已合併 {len(folders)} 個資料夾"
        subfolder_entries = []
        media_items = []
        seen_entries: set[str] = set()
        seen_media: set[str] = set()
        for folder in folders:
            for entry in _collect_folder_entries(ctx, folder):
                key = str(entry.subfolder_path.resolve())
                if key in seen_entries:
                    continue
                seen_entries.add(key)
                subfolder_entries.append(entry)
            _, folder_media = ctx.preview_service.scan_direct_media_for_preview(
                folder,
                ctx.selected_filter_tags,
                ctx.filter_media_video,
                ctx.filter_media_image,
                ctx.filter_duration_min,
                ctx.filter_duration_max,
            )
            for item in folder_media:
                key = str(item.media_path.resolve())
                if key in seen_media:
                    continue
                seen_media.add(key)
                media_items.append(item)

    subfolder_entries = ctx.preview_service.apply_media_entry_filter(
        subfolder_entries,
        ctx.selected_filter_tags,
        ctx.filter_duration_min,
        ctx.filter_duration_max,
        ctx.filter_media_video,
        ctx.filter_media_image,
    )
    subfolder_entries = ctx.preview_service.sorted_entries(subfolder_entries, ctx.preview_sort_mode)
    subfolder_entries = _apply_entry_manual_order(ctx, subfolder_entries, scope_path)

    media_items = ctx.preview_service.sorted_media(media_items, ctx.preview_sort_mode)
    media_items = _apply_media_manual_order(ctx, media_items, scope_path)

    entry_items = [_entry_to_item(e, ctx.store) for e in subfolder_entries]
    tags_map = ctx.preview_service.get_media_tags_map(media_items)
    media_responses = [
        _media_to_item(
            ctx,
            m.media_path,
            m.media_type,
            tags_map.get(str(m.media_path.resolve()), []),
        )
        for m in media_items
    ]
    breadcrumb = ctx.tree_service.get_breadcrumb(str(folders[0]))
    return PreviewFolderResponse(
        scope_label=scope_label,
        scope_path=scope_path,
        entries=entry_items,
        media=media_responses,
        breadcrumb=[{"name": b["name"], "path": b["path"]} for b in breadcrumb],
    )


@router.get("/entries", response_model=PreviewEntriesResponse)
def get_entries(
    paths: list[str] = Query(default=[]),
) -> PreviewEntriesResponse:
    ctx = get_ctx()
    if ctx.store.root_folder is None:
        raise HTTPException(status_code=400, detail="請先設定主資料夾")

    if not paths:
        paths = [str(ctx.store.root_folder.resolve())]

    resolved_paths = [Path(p).resolve() for p in paths]
    root = ctx.store.root_folder.resolve()
    entries: list[SubfolderEntry] = []

    if len(resolved_paths) == 1 and resolved_paths[0] == root:
        for person in ctx.tree_service.get_ordered_people_folders(ctx.config.get("tree_child_order") or {}):
            entries.extend(ctx.store.scan_person_subfolders(person))
        scope_label = root.name
        scope_path = str(root)
    elif len(resolved_paths) == 1:
        p = resolved_paths[0]
        if p == root:
            for person in ctx.tree_service.get_ordered_people_folders(ctx.config.get("tree_child_order") or {}):
                entries.extend(ctx.store.scan_person_subfolders(person))
            scope_label = root.name
        elif p.parent == root:
            entries = ctx.store.scan_person_subfolders(p)
            scope_label = p.name
        else:
            entries = [ctx.preview_service.build_entry_for_folder(p, p.parent.name)]
            if entries[0].person_name == entries[0].subfolder_name:
                scope_label = entries[0].person_name
            else:
                scope_label = f"{entries[0].person_name} / {entries[0].subfolder_name}"
        scope_path = str(p)
    else:
        for p in resolved_paths:
            if p.parent == root:
                entries.extend(ctx.store.scan_person_subfolders(p))
            else:
                entries.append(ctx.preview_service.build_entry_for_folder(p, p.parent.name))
        scope_label = f"已選 {len(resolved_paths)} 個範圍"
        scope_path = str(resolved_paths[0])

    entries = ctx.preview_service.apply_media_entry_filter(
        entries,
        ctx.selected_filter_tags,
        ctx.filter_duration_min,
        ctx.filter_duration_max,
        ctx.filter_media_video,
        ctx.filter_media_image,
    )
    entries = ctx.preview_service.sorted_entries(entries, ctx.preview_sort_mode)

    if ctx.preview_sort_mode == "manual":
        order = ctx.manual_entry_order.get(scope_path, [])
        if order:
            entries = sorted(
                entries,
                key=lambda e: (
                    order.index(str(e.subfolder_path.resolve()))
                    if str(e.subfolder_path.resolve()) in order
                    else 10_000,
                    e.subfolder_name.casefold(),
                ),
            )

    items = [_entry_to_item(e, ctx.store) for e in entries]
    breadcrumb = ctx.tree_service.get_breadcrumb(scope_path)
    return PreviewEntriesResponse(
        scope_label=scope_label,
        scope_path=scope_path,
        items=items,
        breadcrumb=[{"name": b["name"], "path": b["path"]} for b in breadcrumb],
    )


@router.get("/media", response_model=PreviewMediaResponse)
def get_media(
    path: Optional[str] = Query(default=None),
    paths: list[str] = Query(default=[]),
) -> PreviewMediaResponse:
    ctx = get_ctx()
    raw_paths = paths or ([path] if path else [])
    folders = [Path(p).resolve() for p in raw_paths if p]
    if not folders:
        raise HTTPException(status_code=400, detail="請提供資料夾路徑")
    for folder in folders:
        if not folder.is_dir():
            raise HTTPException(status_code=400, detail=f"路徑不是資料夾：{folder}")

    if len(folders) == 1:
        folder = folders[0]
        entry = ctx.preview_service.build_entry_for_folder(folder, folder.parent.name)
        _, display = ctx.preview_service.scan_media_for_preview(
            folder,
            ctx.selected_filter_tags,
            ctx.filter_media_video,
            ctx.filter_media_image,
            ctx.filter_duration_min,
            ctx.filter_duration_max,
        )
        if entry.person_name == entry.subfolder_name:
            scope_label = f"{entry.person_name}（媒體預覽）"
        else:
            scope_label = f"{entry.person_name} / {entry.subfolder_name}（媒體預覽）"
        scope_path = str(folder)
    else:
        display = []
        seen: set[str] = set()
        for folder in folders:
            _, folder_items = ctx.preview_service.scan_media_for_preview(
                folder,
                ctx.selected_filter_tags,
                ctx.filter_media_video,
                ctx.filter_media_image,
                ctx.filter_duration_min,
                ctx.filter_duration_max,
            )
            for item in folder_items:
                key = str(item.media_path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                display.append(item)
        scope_label = f"已合併 {len(folders)} 個資料夾（媒體預覽）"
        scope_path = "||".join(str(p) for p in folders)

    if not display:
        breadcrumb = ctx.tree_service.get_breadcrumb(str(folders[0]))
        return PreviewMediaResponse(
            scope_label=scope_label,
            scope_path=scope_path,
            items=[],
            breadcrumb=[{"name": b["name"], "path": b["path"]} for b in breadcrumb],
        )
    display = ctx.preview_service.sorted_media(display, ctx.preview_sort_mode)

    if ctx.preview_sort_mode == "manual":
        order = ctx.manual_media_order.get(scope_path, [])
        if order:
            display = sorted(
                display,
                key=lambda m: (
                    order.index(str(m.media_path.resolve()))
                    if str(m.media_path.resolve()) in order
                    else 10_000,
                    m.media_path.name.casefold(),
                ),
            )

    tags_map = ctx.preview_service.get_media_tags_map(display)
    items = [
        _media_to_item(
            ctx,
            m.media_path,
            m.media_type,
            tags_map.get(str(m.media_path.resolve()), []),
        )
        for m in display
    ]

    breadcrumb = ctx.tree_service.get_breadcrumb(str(folders[0]))
    return PreviewMediaResponse(
        scope_label=scope_label,
        scope_path=scope_path,
        items=items,
        breadcrumb=[{"name": b["name"], "path": b["path"]} for b in breadcrumb],
    )


@router.get("/tagged-media", response_model=PreviewMediaResponse)
def get_tagged_media(
    paths: list[str] = Query(default=[]),
) -> PreviewMediaResponse:
    ctx = get_ctx()
    if ctx.store.root_folder is None:
        raise HTTPException(status_code=400, detail="請先設定主資料夾")
    if not ctx.selected_filter_tags:
        raise HTTPException(status_code=400, detail="請先選擇至少一個標籤")

    root = ctx.store.root_folder.resolve()
    scope_paths = [Path(p).resolve() for p in paths if p]
    if not scope_paths:
        scope_paths = [root]

    ctx.keyword_service.reconcile_scope(scope_paths)

    display = ctx.preview_service.scan_tagged_media_in_scope(
        scope_paths,
        ctx.selected_filter_tags,
        ctx.filter_media_video,
        ctx.filter_media_image,
        ctx.filter_duration_min,
        ctx.filter_duration_max,
    )
    display = ctx.preview_service.sorted_media(display, ctx.preview_sort_mode)

    if len(scope_paths) == 1:
        scope_path = str(scope_paths[0])
        if scope_paths[0] == root:
            scope_label = f"{root.name}（標籤篩選）"
        else:
            scope_label = f"{scope_paths[0].name}（標籤篩選）"
    else:
        scope_path = "||".join(str(p) for p in scope_paths)
        scope_label = f"已選 {len(scope_paths)} 個範圍（標籤篩選）"

    if ctx.preview_sort_mode == "manual":
        order = ctx.manual_media_order.get(scope_path, [])
        if order:
            display = sorted(
                display,
                key=lambda m: (
                    order.index(str(m.media_path.resolve()))
                    if str(m.media_path.resolve()) in order
                    else 10_000,
                    m.media_path.name.casefold(),
                ),
            )

    tags_map = ctx.preview_service.get_media_tags_map(display)
    items = [
        _media_to_item(
            ctx,
            m.media_path,
            m.media_type,
            tags_map.get(str(m.media_path.resolve()), []),
        )
        for m in display
    ]

    breadcrumb = ctx.tree_service.get_breadcrumb(str(scope_paths[0]))
    return PreviewMediaResponse(
        scope_label=scope_label,
        scope_path=scope_path,
        items=items,
        breadcrumb=[{"name": b["name"], "path": b["path"]} for b in breadcrumb],
    )
