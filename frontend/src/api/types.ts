export type TreeNodeType = 'root' | 'person' | 'subfolder' | 'stub'
export type ViewMode = 'folder' | 'entries' | 'media'
export type SortMode = 'name' | 'time' | 'type' | 'manual'

export interface TreeNode {
  id: string
  name: string
  path: string
  type: TreeNodeType
  children: TreeNode[]
}

export interface BreadcrumbItem {
  name: string
  path: string
}

export interface PreviewSampleItem {
  path: string
  media_type: 'image' | 'video'
}

export interface EntryItem {
  id: string
  person_name: string
  subfolder_name: string
  path: string
  relative_key: string
  preview_path?: string | null
  preview_type?: string | null
  media_count: number
  preview_samples?: PreviewSampleItem[]
}

export interface MediaItem {
  id: string
  path: string
  name: string
  media_type: 'image' | 'video'
  duration_seconds?: number | null
  duration_label?: string | null
  tags: string[]
}

export interface FilterState {
  selected_tags: string[]
  media_video: boolean
  media_image: boolean
  duration_min?: number | null
  duration_max?: number | null
  sort_mode: SortMode
}

export interface PreviewFolderResponse {
  view_mode: 'folder'
  scope_label: string
  scope_path: string
  entries: EntryItem[]
  media: MediaItem[]
  breadcrumb: BreadcrumbItem[]
}

export interface PreviewEntriesResponse {
  view_mode: 'entries'
  scope_label: string
  scope_path: string
  items: EntryItem[]
  breadcrumb: BreadcrumbItem[]
}

export interface PreviewMediaResponse {
  view_mode: 'media'
  scope_label: string
  scope_path: string
  items: MediaItem[]
  breadcrumb: BreadcrumbItem[]
}

export interface ConfigResponse {
  root_folder: string
  has_root: boolean
  migration_message?: string | null
}

export interface TagListResponse {
  all_tags: string[]
  filter_state: FilterState
}

export interface StatusResponse {
  message: string
  ok: boolean
  warnings?: string[] | null
  renamed_paths?: string[] | null
  saved_path?: string | null
  conflicts?: { source_path: string; target_path: string; name: string }[] | null
  deleted_sources?: string[] | null
}
