from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ConfigResponse(BaseModel):
    root_folder: str
    has_root: bool


class SetRootRequest(BaseModel):
    path: str


class TreeNode(BaseModel):
    id: str
    name: str
    path: str
    type: Literal["root", "person", "subfolder", "stub"]
    children: list["TreeNode"] = Field(default_factory=list)


TreeNode.model_rebuild()


class BreadcrumbItem(BaseModel):
    name: str
    path: str


class EntryItem(BaseModel):
    id: str
    person_name: str
    subfolder_name: str
    path: str
    relative_key: str
    preview_path: Optional[str] = None
    preview_type: Optional[str] = None
    media_count: int
    tags: list[str] = Field(default_factory=list)


class MediaItemResponse(BaseModel):
    id: str
    path: str
    name: str
    media_type: Literal["image", "video"]
    duration_seconds: Optional[float] = None
    duration_label: Optional[str] = None


class PreviewEntriesResponse(BaseModel):
    view_mode: Literal["entries"] = "entries"
    scope_label: str
    scope_path: str
    items: list[EntryItem]
    breadcrumb: list[BreadcrumbItem]


class PreviewMediaResponse(BaseModel):
    view_mode: Literal["media"] = "media"
    scope_label: str
    scope_path: str
    items: list[MediaItemResponse]
    breadcrumb: list[BreadcrumbItem]


class FilterState(BaseModel):
    selected_tags: list[str] = Field(default_factory=list)
    media_video: bool = False
    media_image: bool = False
    duration_min: Optional[float] = None
    duration_max: Optional[float] = None
    sort_mode: Literal["name", "time", "type", "manual"] = "name"


class TagListResponse(BaseModel):
    all_tags: list[str]
    filter_state: FilterState


class SetTagsRequest(BaseModel):
    relative_key: str
    tags: list[str]


class DeleteTagsRequest(BaseModel):
    tags: list[str]


class CreateFolderRequest(BaseModel):
    parent_path: str
    name: str


class RenameFolderRequest(BaseModel):
    path: str
    new_name: str


class RenameFileRequest(BaseModel):
    path: str
    new_stem: str


class SaveVideoFrameRequest(BaseModel):
    video_path: str
    image_data_url: Optional[str] = None
    timestamp_seconds: Optional[float] = None


class TransferRequest(BaseModel):
    source_paths: list[str]
    target_folder: str


class MergeFoldersRequest(BaseModel):
    folder_paths: list[str]
    conflict_strategy: Literal["ask", "keep", "skip", "cancel"] = "ask"


class DeleteFilesRequest(BaseModel):
    paths: list[str]


class NumberedRenameRequest(BaseModel):
    paths: list[str]
    base: str
    start_no: int
    is_folder: bool
    allow_overwrite: bool = False


class ReorderRequest(BaseModel):
    scope_path: str
    kind: Literal["entries", "media"]
    ordered_ids: list[str]


class StatusResponse(BaseModel):
    message: str
    ok: bool = True
    renamed_paths: Optional[list[str]] = None
    saved_path: Optional[str] = None
    conflicts: Optional[list[dict[str, str]]] = None
    deleted_sources: Optional[list[str]] = None


class ImportTagsRequest(BaseModel):
    content: str
    format: Literal["json", "csv"]
    merge: bool = True
