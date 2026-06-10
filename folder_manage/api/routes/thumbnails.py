from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from api.deps import get_ctx
from api.constants import ENTRY_THUMBNAIL_SIZE, MEDIA_THUMBNAIL_SIZE
from people_data_store import SubfolderEntry

router = APIRouter(prefix="/api/thumbnails", tags=["thumbnails"])


def _decode_path_param(path: str | None = None, token: str | None = None) -> Path:
    if token:
        padded = token + "=" * (-len(token) % 4)
        try:
            raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="路徑 token 無效") from exc
        return Path(raw).resolve()
    if not path:
        raise HTTPException(status_code=400, detail="缺少檔案路徑")
    return Path(unquote(path)).resolve()


@router.get("/entry")
def get_entry_thumbnail(path: str = Query(...)) -> Response:
    ctx = get_ctx()
    folder = Path(unquote(path)).resolve()
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="資料夾不存在")
    entry = ctx.preview_service.build_entry_for_folder(folder, folder.parent.name)
    image = ctx.thumbnail_service.get_entry_thumbnail(entry)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    return Response(
        content=buf.getvalue(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/media")
def get_media_thumbnail(
    path: str = Query(...),
    media_type: str = Query("image"),
) -> Response:
    ctx = get_ctx()
    file_path = Path(unquote(path)).resolve()
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="檔案不存在")
    image = ctx.thumbnail_service.get_media_thumbnail(file_path, media_type)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    return Response(
        content=buf.getvalue(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/file")
def get_media_file(
    path: str | None = Query(default=None),
    token: str | None = Query(default=None),
) -> FileResponse:
    file_path = _decode_path_param(path, token)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="檔案不存在")
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )
