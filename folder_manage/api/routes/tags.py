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
    return TagListResponse(all_tags=ctx.tag_repo.get_all_tags(), filter_state=_filter_state(ctx))


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
    return TagListResponse(all_tags=ctx.tag_repo.get_all_tags(), filter_state=_filter_state(ctx))


@router.post("/set", response_model=StatusResponse)
def set_tags(body: SetTagsRequest) -> StatusResponse:
    ctx = get_ctx()
    merged = ctx.tag_repo.set_tags(body.relative_key, body.tags)
    return StatusResponse(message=f"已更新標籤：{', '.join(merged) or '（無）'}")


@router.post("/add", response_model=StatusResponse)
def add_tags(body: SetTagsRequest) -> StatusResponse:
    ctx = get_ctx()
    merged = ctx.tag_repo.add_tags(body.relative_key, body.tags)
    return StatusResponse(message=f"已添加標籤：{', '.join(merged)}")


@router.post("/delete", response_model=TagListResponse)
def delete_tags(body: DeleteTagsRequest) -> TagListResponse:
    ctx = get_ctx()
    tags = [tag.strip() for tag in body.tags if tag.strip()]
    if not tags:
        raise HTTPException(status_code=400, detail="請提供要刪除的標籤")
    ctx.tag_repo.remove_tags_everywhere(tags)
    deleted = {tag.casefold() for tag in tags}
    ctx.selected_filter_tags = {
        tag for tag in ctx.selected_filter_tags if tag.casefold() not in deleted
    }
    ctx.preview_service.clear_filter_cache()
    return TagListResponse(all_tags=ctx.tag_repo.get_all_tags(), filter_state=_filter_state(ctx))


@router.get("/export")
def export_tags(format: str = "json") -> PlainTextResponse:
    ctx = get_ctx()
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["subfolder_path", "tags"])
        for key in sorted(ctx.tag_repo._tags_by_key.keys(), key=str.lower):
            writer.writerow([key, ";".join(ctx.tag_repo.get_tags(key))])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    payload = json.dumps(ctx.tag_repo._tags_by_key, ensure_ascii=False, indent=2)
    return PlainTextResponse(payload, media_type="application/json")


@router.post("/import", response_model=StatusResponse)
def import_tags(body: ImportTagsRequest) -> StatusResponse:
    ctx = get_ctx()
    tmp = Path(ctx.tag_repo.base_dir) / "_import_tmp"
    try:
        if body.format == "json":
            tmp.write_text(body.content, encoding="utf-8")
            ctx.tag_repo.import_json(tmp, merge=body.merge)
        else:
            tmp.write_text(body.content, encoding="utf-8-sig")
            ctx.tag_repo.import_csv(tmp, merge=body.merge)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    ctx.preview_service.clear_filter_cache()
    return StatusResponse(message="已匯入標籤")
