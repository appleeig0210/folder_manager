import type {
  ConfigResponse,
  FilterState,
  PreviewEntriesResponse,
  PreviewMediaResponse,
  StatusResponse,
  TagListResponse,
  TreeNode,
  BreadcrumbItem,
} from './types'
import { isTauriRuntime } from '../lib/utils'

const API_BASE = import.meta.env.VITE_API_BASE ?? (isTauriRuntime() ? 'http://127.0.0.1:8765' : '')

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || res.statusText)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('application/json')) return res.json() as Promise<T>
  return res.text() as Promise<T>
}

async function waitForHealth(): Promise<{ status: string }> {
  let lastError: unknown
  // PyInstaller onefile sidecar 首次解壓可能需要十幾秒
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      return await request<{ status: string }>('/api/health')
    } catch (error) {
      lastError = error
      await delay(500)
    }
  }
  throw lastError
}

function dedupeMediaItems<T extends { id: string }>(items: T[]): T[] {
  const seen = new Set<string>()
  const result: T[] = []
  for (const item of items) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    result.push(item)
  }
  return result
}

function encodePathToken(path: string): string {
  const utf8 = new TextEncoder().encode(path)
  let binary = ''
  for (const byte of utf8) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export const api = {
  health: waitForHealth,
  getConfig: () => request<ConfigResponse>('/api/config'),
  setRoot: (path: string) =>
    request<StatusResponse>('/api/config/root', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
  getTree: () => request<TreeNode[]>('/api/tree'),
  expandNode: (path: string) =>
    request<TreeNode[]>(`/api/tree/expand?path=${encodeURIComponent(path)}`),
  getBreadcrumb: (path: string) =>
    request<BreadcrumbItem[]>(`/api/tree/breadcrumb?path=${encodeURIComponent(path)}`),
  getEntries: (paths: string[]) => {
    const qs = paths.map((p) => `paths=${encodeURIComponent(p)}`).join('&')
    return request<PreviewEntriesResponse>(`/api/preview/entries?${qs}`)
  },
  getMedia: (pathOrPaths: string | string[]) => {
    const paths = Array.isArray(pathOrPaths) ? pathOrPaths : [pathOrPaths]
    const qs =
      paths.length === 1
        ? `path=${encodeURIComponent(paths[0])}&paths=${encodeURIComponent(paths[0])}`
        : [
            `path=${encodeURIComponent(paths[0])}`,
            ...paths.map((p) => `paths=${encodeURIComponent(p)}`),
          ].join('&')
    return request<PreviewMediaResponse>(`/api/preview/media?${qs}`).then(async (res) => {
      if (paths.length <= 1 || res.scope_label.startsWith('已合併')) return res

      // Fallback for a still-running old backend that ignores repeated `paths`.
      const settled = await Promise.all(
        paths.map((p) =>
          request<PreviewMediaResponse>(`/api/preview/media?path=${encodeURIComponent(p)}`).catch(() => null),
        ),
      )
      const ok = settled.filter((x): x is PreviewMediaResponse => x !== null)
      if (!ok.length) return res
      return {
        ...res,
        view_mode: 'media',
        scope_label: `已合併 ${paths.length} 個資料夾（媒體預覽）`,
        scope_path: paths.join('||'),
        items: dedupeMediaItems(ok.flatMap((x) => x.items)),
        breadcrumb: ok[0].breadcrumb,
      }
    })
  },
  entryThumbUrl: (path: string, version = 0) =>
    `${API_BASE}/api/thumbnails/entry?path=${encodeURIComponent(path)}&v=${version}`,
  mediaThumbUrl: (path: string, mediaType: string, version = 0) =>
    `${API_BASE}/api/thumbnails/media?path=${encodeURIComponent(path)}&media_type=${mediaType}&v=${version}`,
  mediaFileUrl: (path: string) =>
    `${API_BASE}/api/thumbnails/file?token=${encodePathToken(path)}`,
  getTags: () => request<TagListResponse>('/api/tags'),
  updateFilter: (state: FilterState) =>
    request<TagListResponse>('/api/tags/filter', {
      method: 'PATCH',
      body: JSON.stringify(state),
    }),
  setTags: (relative_key: string, tags: string[]) =>
    request<StatusResponse>('/api/tags/set', {
      method: 'POST',
      body: JSON.stringify({ relative_key, tags }),
    }),
  addTags: (relative_key: string, tags: string[]) =>
    request<StatusResponse>('/api/tags/add', {
      method: 'POST',
      body: JSON.stringify({ relative_key, tags }),
    }),
  deleteTags: (tags: string[]) =>
    request<TagListResponse>('/api/tags/delete', {
      method: 'POST',
      body: JSON.stringify({ tags }),
    }),
  exportTags: async (format: 'json' | 'csv') => {
    const res = await fetch(`${API_BASE}/api/tags/export?format=${format}`)
    return res.text()
  },
  importTags: (content: string, format: 'json' | 'csv', merge = true) =>
    request<StatusResponse>('/api/tags/import', {
      method: 'POST',
      body: JSON.stringify({ content, format, merge }),
    }),
  createFolder: (parent_path: string, name: string) =>
    request<StatusResponse>('/api/files/folder', {
      method: 'POST',
      body: JSON.stringify({ parent_path, name }),
    }),
  renameFolder: (path: string, new_name: string) =>
    request<StatusResponse>('/api/files/folder/rename', {
      method: 'PATCH',
      body: JSON.stringify({ path, new_name }),
    }),
  deleteFolder: (path: string) =>
    request<StatusResponse>(`/api/files/folder?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  renameFile: (path: string, new_stem: string) =>
    request<StatusResponse>('/api/files/file/rename', {
      method: 'PATCH',
      body: JSON.stringify({ path, new_stem }),
    }),
  saveVideoFrame: (video_path: string, image_data_url: string, timestamp_seconds?: number) =>
    request<StatusResponse>('/api/files/video-frame', {
      method: 'POST',
      body: JSON.stringify({ video_path, image_data_url, timestamp_seconds }),
    }),
  deleteFiles: (paths: string[]) =>
    request<StatusResponse>('/api/files/files', {
      method: 'DELETE',
      body: JSON.stringify({ paths }),
    }),
  transfer: (source_paths: string[], target_folder: string) =>
    request<StatusResponse>('/api/files/transfer', {
      method: 'POST',
      body: JSON.stringify({ source_paths, target_folder }),
    }),
  mergeFolders: (folder_paths: string[], conflict_strategy: 'ask' | 'keep' | 'skip' | 'cancel' = 'ask') =>
    request<StatusResponse>('/api/files/folders/merge', {
      method: 'POST',
      body: JSON.stringify({ folder_paths, conflict_strategy }),
    }),
  renameNumbered: (
    paths: string[],
    base: string,
    start_no: number,
    is_folder: boolean,
    allow_overwrite = false,
  ) =>
    request<StatusResponse>('/api/files/rename-numbered', {
      method: 'POST',
      body: JSON.stringify({ paths, base, start_no, is_folder, allow_overwrite }),
    }),
  reorder: (scope_path: string, kind: 'entries' | 'media', ordered_ids: string[]) =>
    request<StatusResponse>('/api/files/reorder', {
      method: 'POST',
      body: JSON.stringify({ scope_path, kind, ordered_ids }),
    }),
  openPath: (path: string) =>
    request<StatusResponse>(`/api/files/open?path=${encodeURIComponent(path)}`, { method: 'POST' }),
}
