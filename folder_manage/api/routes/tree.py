from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_ctx
from api.schemas import BreadcrumbItem, TreeNode

router = APIRouter(prefix="/api/tree", tags=["tree"])


@router.get("", response_model=list[TreeNode])
def get_tree() -> list[TreeNode]:
    ctx = get_ctx()
    child_order = ctx.config.get("tree_child_order") or {}
    nodes = ctx.tree_service.build_tree_nodes(
        selected_filter_tags=ctx.selected_filter_tags,
        want_video=ctx.filter_media_video,
        want_image=ctx.filter_media_image,
        lo_min=ctx.filter_duration_min,
        hi_min=ctx.filter_duration_max,
        child_order=child_order,
    )
    return [TreeNode(**n) for n in nodes]


@router.get("/expand", response_model=list[TreeNode])
def expand_node(path: str = Query(...)) -> list[TreeNode]:
    ctx = get_ctx()
    children = ctx.tree_service.expand_node(path)
    return [TreeNode(**c) for c in children]


@router.get("/breadcrumb", response_model=list[BreadcrumbItem])
def get_breadcrumb(path: str = Query(...)) -> list[BreadcrumbItem]:
    ctx = get_ctx()
    crumbs = ctx.tree_service.get_breadcrumb(path)
    return [BreadcrumbItem(**c) for c in crumbs]
