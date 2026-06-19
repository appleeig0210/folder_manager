from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from api.deps import get_ctx
from api.schemas import DeleteTagsRequest, FilterState, ImportTagsRequest, SetTagsRequest, StatusResponse, TagListResponse

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _filter_state(ctx) -> FilterState:
    return FilterState(
        selected_tags=sorted(ctx.selected_filter_tags),
        media_video=ctx.filter_media_video,
        media_image=ctx.filter_media_image,
        duration_min=ctx.filter_duration_min,
        duration_max=ctx.filter_duration_max,
        sort_mode=ctx.preview_sort_mode,
    )


@router.get("", response_model=TagListResponse)
def list_tags() -> TagListResponse:
    ctx = get_ctx()
    if ctx.store.root_folder is None:
        return TagListResponse(all_tags=[], filter_state=_filter_state(ctx))
    try:
        all_tags = ctx.keyword_service.collect_all_tags(ctx.store)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TagListResponse(all_tags=all_tags, filter_state=_filter_state(ctx))


@router.patch("/filter", response_model=TagListResponse)
def update_filter(state: FilterState) -> TagListResponse:
    ctx = get_ctx()
    ctx.selected_filter_tags = set(state.selected_tags)
    ctx.filter_media_video = state.media_video
    ctx.filter_media_image = state.media_image
    ctx.filter_duration_min = state.duration_min
    ctx.filter_duration_max = state.duration_max
    ctx.preview_sort_mode = state.sort_mode
    ctx.preview_service.clear_filter_cache()
    all_tags = []
    if ctx.store.root_folder is not None:
        try:
            all_tags = ctx.keyword_service.collect_all_tags(ctx.store)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TagListResponse(all_tags=all_tags, filter_state=_filter_state(ctx))


@router.post("/set", response_model=StatusResponse)
def set_tags(body: SetTagsRequest) -> StatusResponse:
    ctx = get_ctx()
    paths = [Path(p) for p in body.paths if (p or "").strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="請提供至少一個媒體檔路徑")
    try:
        updated, warnings = ctx.keyword_service.set_keywords_batch(paths, body.tags)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ctx.preview_service.clear_filter_cache()
    message = f"已更新 {updated} 個媒體檔標籤"
    if warnings:
        message += f"（{len(warnings)} 個失敗）"
    return StatusResponse(message=message)


@router.post("/add", response_model=StatusResponse)
def add_tags(body: SetTagsRequest) -> StatusResponse:
    ctx = get_ctx()
    paths = [Path(p) for p in body.paths if (p or "").strip()]
    tags = [tag.strip() for tag in body.tags if tag.strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="請提供至少一個媒體檔路徑")
    if not tags:
        raise HTTPException(status_code=400, detail="請提供至少一個標籤")
    try:
        updated, warnings = ctx.keyword_service.add_keywords_batch(paths, tags)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ctx.preview_service.clear_filter_cache()
    message = f"已為 {updated} 個媒體檔添加標籤：{', '.join(tags)}"
    if warnings:
        message += f"（{len(warnings)} 個失敗）"
    return StatusResponse(message=message)


@router.post("/delete", response_model=TagListResponse)
def delete_tags(body: DeleteTagsRequest) -> TagListResponse:
    ctx = get_ctx()
    tags = [tag.strip() for tag in body.tags if tag.strip()]
    if not tags:
        raise HTTPException(status_code=400, detail="請提供要刪除的標籤")
    if ctx.store.root_folder is None:
        raise HTTPException(status_code=400, detail="請先設定主資料夾")
    try:
        ctx.keyword_service.remove_tags_everywhere(ctx.store, tags)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    deleted = {tag.casefold() for tag in tags}
    ctx.selected_filter_tags = {
        tag for tag in ctx.selected_filter_tags if tag.casefold() not in deleted
    }
    ctx.preview_service.clear_filter_cache()
    all_tags = ctx.keyword_service.collect_all_tags(ctx.store)
    return TagListResponse(all_tags=all_tags, filter_state=_filter_state(ctx))


@router.post("/invalidate", response_model=StatusResponse)
def invalidate_cache() -> StatusResponse:
    ctx = get_ctx()
    ctx.keyword_service.invalidate_all()
    ctx.preview_service.clear_filter_cache()
    return StatusResponse(message="已清除媒體標籤快取")


@router.get("/export")
def export_tags(format: str = "json") -> PlainTextResponse:
    ctx = get_ctx()
    if ctx.store.root_folder is None:
        raise HTTPException(status_code=400, detail="請先設定主資料夾")
    try:
        payload = ctx.keyword_service.export_map(ctx.store)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["file_path", "tags"])
        for key in sorted(payload.keys(), key=str.lower):
            writer.writerow([key, ";".join(payload[key])])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    return PlainTextResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
    )


@router.post("/import", response_model=StatusResponse)
def import_tags(body: ImportTagsRequest) -> StatusResponse:
    ctx = get_ctx()
    if ctx.store.root_folder is None:
        raise HTTPException(status_code=400, detail="請先設定主資料夾")
    try:
        if body.format == "json":
            payload = json.loads(body.content)
            if not isinstance(payload, dict):
                raise ValueError("JSON 必須為 {file_path: [tags]} 格式")
            imported = {
                str(key): [str(t) for t in value if str(t).strip()]
                for key, value in payload.items()
                if isinstance(value, list)
            }
        else:
            imported: dict[str, list[str]] = {}
            reader = csv.DictReader(io.StringIO(body.content))
            for row in reader:
                key = (row.get("file_path") or row.get("subfolder_path") or "").strip()
                tags_text = (row.get("tags") or "").strip()
                if not key:
                    continue
                tags = [x.strip() for x in tags_text.split(";") if x.strip()]
                imported[key] = tags
        count = ctx.keyword_service.import_map(ctx.store, imported, merge=body.merge)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ctx.preview_service.clear_filter_cache()
    return StatusResponse(message=f"已匯入 {count} 筆媒體標籤")
