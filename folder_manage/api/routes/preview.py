from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_ctx
from api.schemas import EntryItem, MediaItemResponse, PreviewEntriesResponse, PreviewMediaResponse
from api.services.thumbnail_service import ThumbnailService
from people_data_store import SubfolderEntry

router = APIRouter(prefix="/api/preview", tags=["preview"])


def _entry_to_item(entry: SubfolderEntry) -> EntryItem:
    return EntryItem(
        id=str(entry.subfolder_path.resolve()),
        person_name=entry.person_name,
        subfolder_name=entry.subfolder_name,
        path=str(entry.subfolder_path.resolve()),
        relative_key=entry.relative_key,
        preview_path=str(entry.preview_path.resolve()) if entry.preview_path else None,
        preview_type=entry.preview_type,
        media_count=entry.media_count,
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

    items = [_entry_to_item(e) for e in entries]
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
