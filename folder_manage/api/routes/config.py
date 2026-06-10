from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.deps import get_ctx
from api.schemas import ConfigResponse, SetRootRequest, StatusResponse

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    ctx = get_ctx()
    root = ctx.store.root_folder
    return ConfigResponse(
        root_folder=str(root) if root else "",
        has_root=root is not None,
    )


def _normalize_path_input(raw: str) -> str:
    return raw.strip().strip('"').strip("'")


@router.post("/root", response_model=StatusResponse)
def set_root_folder(body: SetRootRequest) -> StatusResponse:
    ctx = get_ctx()
    path = Path(_normalize_path_input(body.path)).expanduser()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail="資料夾不存在")
    ctx.store.set_root_folder(path)
    ctx.config["root_folder"] = str(path.resolve())
    ctx.save_config()
    ctx.preview_service.clear_filter_cache()
    return StatusResponse(message=f"已設定主資料夾：{path}")
