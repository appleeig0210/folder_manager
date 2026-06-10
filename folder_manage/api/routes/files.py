from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_ctx
from api.schemas import (
    CreateFolderRequest,
    DeleteFilesRequest,
    NumberedRenameRequest,
    RenameFileRequest,
    RenameFolderRequest,
    ReorderRequest,
    StatusResponse,
    TransferRequest,
)

router = APIRouter(prefix="/api/files", tags=["files"])


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
    try:
        new_path = ctx.file_ops.rename_folder(Path(body.path), body.new_name)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    try:
        new_path = ctx.file_ops.rename_file(Path(body.path), body.new_stem)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(message=f"已重新命名：{new_path.name}")


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
    return StatusResponse(message=f"已重新命名 {len(paths)} 個項目")


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
