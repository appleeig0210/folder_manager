from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_ctx
from api.schemas import (
    CreateFolderRequest,
    DeleteFilesRequest,
    MergeFoldersRequest,
    NumberedRenameRequest,
    RenameFileRequest,
    RenameFolderRequest,
    ReorderRequest,
    SaveVideoFrameRequest,
    StatusResponse,
    TransferRequest,
)

router = APIRouter(prefix="/api/files", tags=["files"])


def _remap_path_value(value: str, path_pairs: list[tuple[Path, Path]]) -> str:
    path = Path(value).resolve()
    for old, new in sorted(path_pairs, key=lambda pair: len(str(pair[0])), reverse=True):
        try:
            relative = path.relative_to(old)
        except ValueError:
            continue
        return str((new / relative).resolve())
    return str(path)


def _remap_scope_path(scope_path: str, path_pairs: list[tuple[Path, Path]]) -> str:
    if "||" not in scope_path:
        return _remap_path_value(scope_path, path_pairs)
    return "||".join(_remap_path_value(part, path_pairs) for part in scope_path.split("||"))


def _sync_manual_order_after_rename(order_map: dict[str, list[str]], plan: list[tuple[Path, Path]]) -> None:
    path_pairs = [(old.resolve(), new.resolve()) for old, new in plan]
    if not path_pairs:
        return

    updated: dict[str, list[str]] = {}
    for scope_path, order in order_map.items():
        next_scope = _remap_scope_path(scope_path, path_pairs)
        next_order: list[str] = []
        seen: set[str] = set()
        for item_id in order:
            next_id = _remap_path_value(item_id, path_pairs)
            if next_id in seen:
                continue
            seen.add(next_id)
            next_order.append(next_id)

        if next_scope in updated:
            existing = set(updated[next_scope])
            updated[next_scope].extend(item_id for item_id in next_order if item_id not in existing)
        else:
            updated[next_scope] = next_order

    order_map.clear()
    order_map.update(updated)


def _remove_deleted_folders_from_tree_order(ctx, deleted_folders: list[str]) -> None:
    order_map = ctx.config.get("tree_child_order")
    if not isinstance(order_map, dict):
        return

    changed = False
    for raw_path in deleted_folders:
        folder = Path(raw_path).resolve()
        parent_key = str(folder.parent.resolve())
        names = order_map.get(parent_key)
        if isinstance(names, list) and folder.name in names:
            order_map[parent_key] = [name for name in names if name != folder.name]
            changed = True
        folder_key = str(folder)
        if folder_key in order_map:
            del order_map[folder_key]
            changed = True

    if changed:
        ctx.save_config()


@router.post("/folder", response_model=StatusResponse)
def create_folder(body: CreateFolderRequest) -> StatusResponse:
    ctx = get_ctx()
    try:
        new_path = ctx.file_ops.create_folder(Path(body.parent_path), body.name)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(message=f"已新增資料夾：{new_path}")


@router.patch("/folder/rename", response_model=StatusResponse)
def rename_folder(body: RenameFolderRequest) -> StatusResponse:
    ctx = get_ctx()
    old_path = Path(body.path).resolve()
    try:
        new_path = ctx.file_ops.rename_folder(old_path, body.new_name)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _sync_manual_order_after_rename(ctx.manual_entry_order, [(old_path, new_path)])
    _sync_manual_order_after_rename(ctx.manual_media_order, [(old_path, new_path)])
    return StatusResponse(message=f"已重新命名：{new_path.name}")


@router.delete("/folder", response_model=StatusResponse)
def delete_folder(path: str) -> StatusResponse:
    ctx = get_ctx()
    try:
        count = ctx.file_ops.delete_folder(Path(path))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(message=f"已刪除資料夾（移除 {count} 個檔案）")


@router.patch("/file/rename", response_model=StatusResponse)
def rename_file(body: RenameFileRequest) -> StatusResponse:
    ctx = get_ctx()
    old_path = Path(body.path).resolve()
    try:
        new_path = ctx.file_ops.rename_file(old_path, body.new_stem)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _sync_manual_order_after_rename(ctx.manual_media_order, [(old_path, new_path)])
    return StatusResponse(message=f"已重新命名：{new_path.name}")


@router.post("/video-frame", response_model=StatusResponse)
def save_video_frame(body: SaveVideoFrameRequest) -> StatusResponse:
    ctx = get_ctx()
    try:
        video_path = Path(body.video_path)
        if body.timestamp_seconds is not None:
            target = ctx.file_ops.build_next_video_frame_path(video_path)
            try:
                saved_path = ctx.thumbnail_service.extract_video_frame_png(
                    video_path,
                    target,
                    body.timestamp_seconds,
                )
                ctx.store.clear_cache()
            except Exception:
                if not body.image_data_url:
                    raise
                prefix, encoded = body.image_data_url.split(",", 1)
                if "image/png" not in prefix:
                    raise ValueError("圖片格式必須是 PNG")
                png_data = base64.b64decode(encoded, validate=True)
                saved_path = ctx.file_ops.save_video_frame_png(video_path, png_data)
        else:
            if not body.image_data_url:
                raise ValueError("缺少圖片資料")
            prefix, encoded = body.image_data_url.split(",", 1)
            if "image/png" not in prefix:
                raise ValueError("圖片格式必須是 PNG")
            png_data = base64.b64decode(encoded, validate=True)
            saved_path = ctx.file_ops.save_video_frame_png(video_path, png_data)
        ctx.preview_service.clear_filter_cache()
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(
        message=f"已儲存圖片：{saved_path.name}",
        saved_path=str(saved_path),
    )


@router.delete("/files", response_model=StatusResponse)
def delete_files(body: DeleteFilesRequest) -> StatusResponse:
    ctx = get_ctx()
    deleted, failed = ctx.file_ops.delete_files([Path(p) for p in body.paths])
    return StatusResponse(message=f"已刪除 {deleted} 個，失敗 {failed} 個")


@router.post("/transfer", response_model=StatusResponse)
def transfer_items(body: TransferRequest) -> StatusResponse:
    ctx = get_ctx()
    sources = [Path(p).resolve() for p in body.source_paths]
    target = Path(body.target_folder).resolve()
    folders = [p for p in sources if p.is_dir()]
    files = [p for p in sources if p.is_file()]
    messages: list[str] = []
    if folders:
        for folder in folders:
            try:
                result = ctx.file_ops.transfer_folder_content(folder, target)
                messages.append(
                    f"{folder.name}: 搬移 {result['moved_count']}，改名 {result['renamed_count']}"
                )
            except Exception as exc:
                messages.append(f"{folder.name}: 失敗 {exc}")
    if files:
        try:
            result = ctx.file_ops.transfer_files(files, target)
            messages.append(
                f"檔案: 移動 {result['moved_count']}，改名 {result['renamed_count']}"
            )
        except Exception as exc:
            messages.append(f"檔案轉移失敗: {exc}")
    return StatusResponse(message="；".join(messages) or "完成")


@router.post("/folders/merge", response_model=StatusResponse)
def merge_folders(body: MergeFoldersRequest) -> StatusResponse:
    ctx = get_ctx()
    paths = [Path(p).resolve() for p in body.folder_paths]
    try:
        conflicts = ctx.file_ops.find_folder_merge_conflicts(paths)
        if body.conflict_strategy == "ask" and conflicts:
            sample = "、".join(conflict["name"] for conflict in conflicts[:3])
            suffix = "…" if len(conflicts) > 3 else ""
            return StatusResponse(
                ok=False,
                message=f"發現 {len(conflicts)} 個同名項目：{sample}{suffix}",
                conflicts=conflicts,
            )
        if body.conflict_strategy == "cancel":
            return StatusResponse(message="已取消資料夾合併")

        result = ctx.file_ops.merge_selected_folders(
            paths,
            "keep" if body.conflict_strategy == "ask" else body.conflict_strategy,
        )
    except (ValueError, FileExistsError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _remove_deleted_folders_from_tree_order(ctx, result["deleted_sources"])
    return StatusResponse(
        message=(
            f"已合併至 {Path(result['target_folder']).name}："
            f"搬移 {result['moved_count']}，改名 {result['renamed_count']}，"
            f"略過 {result['skipped_count']}，刪除來源資料夾 {result['deleted_count']} 個"
        ),
        deleted_sources=result["deleted_sources"],
    )


@router.post("/rename-numbered", response_model=StatusResponse)
def rename_numbered(body: NumberedRenameRequest) -> StatusResponse:
    ctx = get_ctx()
    paths = [Path(p).resolve() for p in body.paths]
    if body.is_folder:
        if not ctx.file_ops.is_valid_folder_basename(body.base):
            raise HTTPException(status_code=400, detail="命名規則無效")
    else:
        if not ctx.file_ops.is_valid_file_stem(body.base):
            raise HTTPException(status_code=400, detail="命名規則無效")
    plan = ctx.file_ops.build_numbered_plan(paths, body.base, body.start_no, is_folder=body.is_folder)
    try:
        ctx.file_ops.apply_rename_plan(plan, is_folder=body.is_folder)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _sync_manual_order_after_rename(ctx.manual_entry_order, plan)
    _sync_manual_order_after_rename(ctx.manual_media_order, plan)
    return StatusResponse(
        message=f"已重新命名 {len(paths)} 個項目",
        renamed_paths=[str(new.resolve()) for _old, new in plan],
    )


@router.post("/reorder", response_model=StatusResponse)
def reorder_items(body: ReorderRequest) -> StatusResponse:
    ctx = get_ctx()
    if body.kind == "entries":
        ctx.manual_entry_order[body.scope_path] = list(body.ordered_ids)
        ctx.preview_sort_mode = "manual"
    else:
        ctx.manual_media_order[body.scope_path] = list(body.ordered_ids)
        ctx.preview_sort_mode = "manual"
    return StatusResponse(message="已更新排序")


@router.post("/open", response_model=StatusResponse)
def open_path(path: str = Query(...)) -> StatusResponse:
    ctx = get_ctx()
    try:
        ctx.file_ops.open_path_external(Path(path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(message="已開啟")
