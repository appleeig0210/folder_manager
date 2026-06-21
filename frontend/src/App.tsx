import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api/client'
import type {
  EntryItem,
  FilterState,
  MediaItem,
  TreeNode,
  ViewMode,
} from './api/types'
import { AppShell } from './components/layout/AppShell'
import { TagFilterBar } from './components/filters/TagFilterBar'
import { MediaFilterBar } from './components/filters/MediaFilterBar'
import { SidebarTree } from './components/navigation/SidebarTree'
import { PreviewGrid } from './components/preview/PreviewGrid'
import { SelectionToolbar } from './components/preview/SelectionToolbar'
import { MediaLightbox } from './components/media/MediaLightbox'
import { ContextMenu, type ContextMenuItem } from './components/ui/ContextMenu'
import { Button } from './components/ui/Button'
import { useTextPrompt } from './components/ui/TextPromptProvider'
import { isTauriRuntime, normalizeFolderPath } from './lib/utils'
import { getPlatformLabel, isDesktopApp } from './lib/platform'
import { isWebLimitedBannerDismissed, WebLimitedBanner } from './components/layout/WebLimitedBanner'
import { foldCase } from './lib/foldCase'

const DEFAULT_FILTER: FilterState = {
  selected_tags: [],
  media_video: false,
  media_image: false,
  duration_min: null,
  duration_max: null,
  sort_mode: 'name',
}

const THEME_STORAGE_KEY = 'people-folder-manager-theme'

function getInitialDarkMode(): boolean {
  return window.localStorage.getItem(THEME_STORAGE_KEY) === 'dark'
}

const filenameCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

type FolderMergeConflict = { source_path: string; target_path: string; name: string }
type FolderMergeStrategy = 'keep' | 'skip'

function normalizeId(id: string): string {
  return id.replaceAll('\\', '/').toLocaleLowerCase()
}

function replacePathFileName(path: string, fileName: string): string {
  const separatorIndex = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  if (separatorIndex < 0) return fileName
  return `${path.slice(0, separatorIndex + 1)}${fileName}`
}

function buildFallbackRenamedIds(paths: string[], base: string, startNo: number, isFolder: boolean): string[] {
  return paths.map((path, index) => {
    const fileName = path.split(/[/\\]/).pop() ?? ''
    const suffix = isFolder ? '' : fileName.match(/\.[^.]+$/)?.[0] ?? ''
    return replacePathFileName(path, `${base}-${startNo + index}${suffix}`)
  })
}

function reorderRenamedItems<T extends { id: string }>(
  items: T[],
  orderBeforeRename: string[],
  renameMap: Map<string, string>,
  getName: (item: T) => string,
): T[] {
  const itemById = new Map(items.map((item) => [normalizeId(item.id), item]))
  const renamedSet = new Set(Array.from(renameMap.values(), normalizeId))
  const ordered = orderBeforeRename
    .map((id) => itemById.get(normalizeId(renameMap.get(id) ?? id)))
    .filter((item): item is T => Boolean(item))
  const seen = new Set(ordered.map((item) => item.id))
  ordered.push(...items.filter((item) => !seen.has(item.id)))

  const renamedQueue = ordered
    .filter((item) => renamedSet.has(normalizeId(item.id)))
    .sort((a, b) => filenameCollator.compare(getName(a), getName(b)))
  const unchanged = ordered.filter((item) => !renamedSet.has(normalizeId(item.id)))
  const result: T[] = []
  let nextRenamedIndex = 0

  for (const item of unchanged) {
    while (
      nextRenamedIndex < renamedQueue.length &&
      filenameCollator.compare(getName(renamedQueue[nextRenamedIndex]), getName(item)) <= 0
    ) {
      result.push(renamedQueue[nextRenamedIndex++])
    }
    result.push(item)
  }

  result.push(...renamedQueue.slice(nextRenamedIndex))
  return result
}

function getGridItems(viewMode: ViewMode, entries: EntryItem[], media: MediaItem[]): Array<EntryItem | MediaItem> {
  if (viewMode === 'folder') return [...entries, ...media]
  if (viewMode === 'entries') return entries
  return media
}

export default function App() {
  const { promptText, confirmAction } = useTextPrompt()
  const [config, setConfig] = useState({ root_folder: '', has_root: false })
  const [tree, setTree] = useState<TreeNode[]>([])
  const [selectedTreePaths, setSelectedTreePaths] = useState<string[]>([])
  const [selectedTreeTypes, setSelectedTreeTypes] = useState<Record<string, TreeNode['type']>>({})
  const [viewMode, setViewMode] = useState<ViewMode>('folder')
  const [entries, setEntries] = useState<EntryItem[]>([])
  const [media, setMedia] = useState<MediaItem[]>([])
  const [scopeLabel, setScopeLabel] = useState('未選擇')
  const [scopePath, setScopePath] = useState('')
  const [breadcrumb, setBreadcrumb] = useState<{ name: string; path: string }[]>([])
  const [status, setStatus] = useState('就緒')
  const [allTags, setAllTags] = useState<string[]>([])
  const [filter, setFilter] = useState<FilterState>(DEFAULT_FILTER)
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [anchorIndex, setAnchorIndex] = useState<number | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [darkMode, setDarkMode] = useState(getInitialDarkMode)
  const [webBannerDismissed, setWebBannerDismissed] = useState(isWebLimitedBannerDismissed)
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; targetId: string } | null>(null)
  const [sidebarContextMenu, setSidebarContextMenu] = useState<{ x: number; y: number; paths: string[] } | null>(null)
  const [tagContextMenu, setTagContextMenu] = useState<{ x: number; y: number; tag: string } | null>(null)
  const [folderMergePrompt, setFolderMergePrompt] = useState<{
    paths: string[]
    message: string
    conflicts: FolderMergeConflict[]
  } | null>(null)
  const [sidebarPrunePaths, setSidebarPrunePaths] = useState<string[]>([])
  const [treeRevision, setTreeRevision] = useState(0)
  const [loading, setLoading] = useState(false)
  const [initializing, setInitializing] = useState(true)
  const [deletingTags, setDeletingTags] = useState<Set<string>>(() => new Set())
  const [thumbnailVersion, setThumbnailVersion] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!sidebarPrunePaths.length) return
    const id = window.setTimeout(() => setSidebarPrunePaths([]), 0)
    return () => window.clearTimeout(id)
  }, [sidebarPrunePaths])

  const applyTheme = (dark: boolean) => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    window.localStorage.setItem(THEME_STORAGE_KEY, dark ? 'dark' : 'light')
    setDarkMode(dark)
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  const refreshTree = useCallback(async () => {
    const nodes = await api.getTree()
    setTree(nodes)
  }, [])

  const loadTags = useCallback(async () => {
    const res = await api.getTags()
    setAllTags(res.all_tags)
    setFilter(res.filter_state)
  }, [])

  const loadFolder = useCallback(async (
    pathOrPaths: string | string[],
    options?: { clearPreview?: boolean },
  ) => {
    setLoading(true)
    setViewMode('folder')
    if (options?.clearPreview) {
      setEntries([])
      setMedia([])
      setSelectedIds(new Set())
    }
    try {
      const res = await api.getFolder(pathOrPaths)
      setViewMode('folder')
      setEntries(res.entries)
      setMedia(res.media)
      setScopeLabel(res.scope_label)
      setScopePath(res.scope_path)
      setBreadcrumb(res.breadcrumb)
      setSelectedIds(new Set())
      setStatus(`已載入 ${res.entries.length} 個資料夾、${res.media.length} 個媒體`)
      return res
    } catch (e) {
      setStatus(String(e))
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const loadTaggedMedia = useCallback(async (paths: string[]) => {
    setLoading(true)
    setViewMode('media')
    setMedia([])
    try {
      const res = await api.getTaggedMedia(paths)
      setViewMode('media')
      setMedia(res.items)
      setEntries([])
      setScopeLabel(res.scope_label)
      setScopePath(res.scope_path)
      setBreadcrumb(res.breadcrumb)
      setSelectedIds(new Set())
      setStatus(`已載入 ${res.items.length} 個符合標籤的媒體`)
      return res
    } catch (e) {
      setViewMode('media')
      setEntries([])
      setMedia([])
      setScopeLabel('標籤篩選載入失敗')
      setBreadcrumb([])
      setStatus(String(e))
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const getTagFilterScopePaths = useCallback((): string[] => {
    if (selectedTreePaths.length) return selectedTreePaths
    if (config.root_folder) return [config.root_folder]
    return []
  }, [config.root_folder, selectedTreePaths])

  const init = useCallback(async () => {
    setInitializing(true)
    try {
      await api.health()
      const cfg = await api.getConfig()
      setConfig(cfg)
      await loadTags()
      await refreshTree()
      if (cfg.has_root && cfg.root_folder) {
        await loadFolder(cfg.root_folder)
        setSelectedTreePaths([cfg.root_folder])
        setSelectedTreeTypes({ [cfg.root_folder]: 'root' })
      }
      setStatus(cfg.migration_message || '就緒')
    } catch (e) {
      setStatus(`無法連線後端：${e}`)
    } finally {
      setInitializing(false)
    }
  }, [loadFolder, loadTags, refreshTree])

  useEffect(() => {
    init()
  }, [init])

  const toggleTag = (tag: string) => {
    const key = foldCase(tag)
    const alreadySelected = filter.selected_tags.some((selected) => foldCase(selected) === key)
    const selected = alreadySelected
      ? filter.selected_tags.filter((t) => foldCase(t) !== key)
      : [...filter.selected_tags, tag]
    updateFilter({ selected_tags: selected })
  }

  const findTreeNode = useCallback((path: string, nodes: TreeNode[] = tree): TreeNode | null => {
    for (const candidate of nodes) {
      if (candidate.path === path) return candidate
      const child = findTreeNode(path, candidate.children)
      if (child) return child
    }
    return null
  }, [tree])

  const normalizePath = (path: string) => path.replaceAll('\\', '/').replace(/\/+$/, '').toLocaleLowerCase()

  const getPathDepthFromRoot = useCallback((path: string) => {
    if (!config.root_folder) return 0
    const root = normalizePath(config.root_folder)
    const target = normalizePath(path)
    if (target === root) return 0
    if (!target.startsWith(`${root}/`)) return 0
    const relative = target.slice(root.length + 1)
    return relative.split('/').filter(Boolean).length
  }, [config.root_folder])

  const classifyTreePath = useCallback((path: string, fallback?: TreeNode['type']): TreeNode['type'] => {
    const depth = getPathDepthFromRoot(path)
    if (depth === 0) return 'root'
    if (depth === 1) return 'person'
    if (depth >= 2) return 'subfolder'
    return fallback ?? 'subfolder'
  }, [getPathDepthFromRoot])

  const reloadPreviewForSelection = useCallback(
    async (activeFilter: FilterState, treePaths: string[]) => {
      if (activeFilter.selected_tags.length > 0) {
        const scope = treePaths.length ? treePaths : config.root_folder ? [config.root_folder] : []
        if (scope.length) await loadTaggedMedia(scope)
        return
      }
      if (!treePaths.length) return
      await loadFolder(treePaths)
    },
    [config.root_folder, loadFolder, loadTaggedMedia],
  )

  const updateFilter = async (patch: Partial<FilterState>) => {
    const next = { ...filter, ...patch }
    setFilter(next)
    const res = await api.updateFilter(next)
    setAllTags(res.all_tags)
    setFilter(res.filter_state)
    if ('selected_tags' in patch) {
      setTreeRevision((version) => version + 1)
    }
    await refreshTree()
    await reloadPreviewForSelection(res.filter_state, selectedTreePaths)
  }

  const reloadCurrentPreview = useCallback(async () => {
    if (filter.selected_tags.length > 0) {
      const scope = getTagFilterScopePaths()
      if (scope.length) await loadTaggedMedia(scope)
      return
    }
    const paths = selectedTreePaths.length
      ? selectedTreePaths
      : scopePath.includes('||')
        ? scopePath.split('||').filter(Boolean)
        : scopePath
          ? [scopePath]
          : []
    if (paths.length) await loadFolder(paths)
  }, [filter.selected_tags, getTagFilterScopePaths, loadFolder, loadTaggedMedia, scopePath, selectedTreePaths])

  const handleTreeSelect = async (paths: string[], node: TreeNode) => {
    setSelectedTreePaths(paths)
    const nextTypes: Record<string, TreeNode['type']> = {}
    for (const path of paths) {
      const knownNode = path === node.path ? node : findTreeNode(path)
      nextTypes[path] = classifyTreePath(path, knownNode?.type ?? selectedTreeTypes[path])
    }
    setSelectedTreeTypes(nextTypes)

    if (filter.selected_tags.length > 0) {
      await loadTaggedMedia(paths.length ? paths : config.root_folder ? [config.root_folder] : [])
      return
    }

    await loadFolder(paths.length ? paths : config.root_folder ? [config.root_folder] : [], {
      clearPreview: true,
    })
  }

  const handleNavigate = async (path: string) => {
    setSelectedTreePaths([path])
    const node = findTreeNode(path)
    setSelectedTreeTypes({ [path]: classifyTreePath(path, node?.type) })
    if (filter.selected_tags.length > 0) {
      await loadTaggedMedia([path])
      return
    }
    await loadFolder(path, { clearPreview: true })
  }

  const handleSelect = (id: string, e: React.MouseEvent, index: number) => {
    const items = getGridItems(viewMode, entries, media)
    if (e.shiftKey && anchorIndex !== null) {
      const [lo, hi] = [anchorIndex, index].sort((a, b) => a - b)
      const range = items.slice(lo, hi + 1).map((it) => it.id)
      setSelectedIds(new Set(range))
      return
    }
    if (e.ctrlKey || e.metaKey) {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
      setAnchorIndex(index)
      return
    }
    if (selectedIds.has(id)) {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      if (selectedIds.size <= 1) {
        setAnchorIndex(null)
      }
      return
    }
    setSelectedIds(new Set([id]))
    setAnchorIndex(index)
  }

  const handleDoubleClickEntry = async (item: EntryItem) => {
    setSelectedTreePaths([item.path])
    setSelectedTreeTypes({ [item.path]: classifyTreePath(item.path, 'subfolder') })
    await loadFolder(item.path, { clearPreview: true })
  }

  const getContextItems = (targetId: string): ContextMenuItem[] => {
    const entry = entries.find((e) => e.id === targetId)
    const mediaItem = media.find((m) => m.id === targetId)
    const items: ContextMenuItem[] = []

    if (entry) {
      const targetPaths =
        selectedIds.has(entry.id) && selectedIds.size > 1 ? selectedPaths : [entry.path]
      items.push(
        { label: '新增資料夾…', onClick: () => promptCreateFolder(entry.path) },
        { separator: true, label: '', onClick: () => {} },
        { label: '打開目標資料夾', onClick: () => api.openPath(entry.path) },
        { label: '重新命名資料夾', onClick: () => promptRenameFolder(entry.path, entry.subfolder_name) },
        { label: targetPaths.length > 1 ? `序號命名已選取項目（${targetPaths.length}）` : '序號命名', onClick: () => promptRenameNumbered(targetPaths) },
        { label: '轉移資料夾內容到…', onClick: () => promptTransfer(targetPaths) },
        { separator: true, label: '', onClick: () => {} },
        { label: '刪除資料夾', danger: true, onClick: () => confirmDeleteFolder(entry.path) },
      )
    } else if (mediaItem) {
      const targetPaths =
        selectedIds.has(mediaItem.id) && selectedIds.size > 1 ? selectedPaths : [mediaItem.path]
      items.push(
        { label: '以程式開啟', onClick: () => api.openPath(mediaItem.path) },
      )
      if (targetPaths.length === 1) {
        items.push({
          label: '編輯標籤…',
          onClick: () => promptEditTags(targetPaths, mediaItem.tags),
        })
      }
      items.push(
        { label: targetPaths.length > 1 ? `添加標籤（${targetPaths.length}）` : '添加標籤…', onClick: () => promptAddTags(targetPaths) },
        { label: '重新命名檔案', onClick: () => promptRenameFile(mediaItem.path) },
        { label: targetPaths.length > 1 ? `序號命名已選取項目（${targetPaths.length}）` : '序號命名', onClick: () => promptRenameNumbered(targetPaths) },
        { label: '轉移已選取項目到…', onClick: () => promptTransfer(targetPaths) },
        { separator: true, label: '', onClick: () => {} },
        { label: '刪除檔案', danger: true, onClick: () => confirmDeleteFiles([mediaItem.path]) },
      )
    }
    return items
  }

  const getSidebarContextItems = (paths: string[]): ContextMenuItem[] => {
    if (paths.length < 2) return []
    return [{ label: '合併資料夾', onClick: () => promptMergeFolders(paths) }]
  }

  const getTagContextItems = (tag: string): ContextMenuItem[] => {
    if (deletingTags.size > 0) {
      return [
        {
          label: '正在刪除中，請等候…',
          onClick: () => setStatus('正在刪除中，請等候…'),
        },
      ]
    }
    const selectedTags = filter.selected_tags
    const tagSelected = selectedTags.some((selected) => foldCase(selected) === foldCase(tag))
    const targetTags = tagSelected && selectedTags.length > 1 ? selectedTags : [tag]
    return [
      {
        label: targetTags.length > 1 ? `刪除已選取標籤（${targetTags.length}）` : '刪除標籤',
        danger: true,
        onClick: () => confirmDeleteTags(targetTags),
      },
    ]
  }

  const reloadAfterFolderMerge = async (targetPath: string, deletedSources: string[]) => {
    setSelectedTreePaths([targetPath])
    const node = findTreeNode(targetPath)
    const targetType = classifyTreePath(targetPath, node?.type)
    setSelectedTreeTypes({ [targetPath]: targetType })
    setSidebarPrunePaths(deletedSources)
    await refreshTree()
    setTreeRevision((version) => version + 1)
    await loadFolder(targetPath)
  }

  const runFolderMerge = async (paths: string[], strategy: FolderMergeStrategy) => {
    setLoading(true)
    setStatus(strategy === 'keep' ? '正在合併資料夾並保留同名項目…' : '正在合併資料夾並略過同名項目…')
    try {
      const res = await api.mergeFolders(paths, strategy)
      setThumbnailVersion((version) => version + 1)
      setFolderMergePrompt(null)
      setStatus(res.message)
      await reloadAfterFolderMerge(paths[0], res.deleted_sources ?? [])
    } catch (e) {
      setStatus(`合併資料夾失敗：${e}`)
    } finally {
      setLoading(false)
    }
  }

  const promptMergeFolders = async (paths: string[]) => {
    if (paths.length < 2) return
    setLoading(true)
    setStatus('正在檢查資料夾合併衝突…')
    try {
      const res = await api.mergeFolders(paths, 'ask')
      if (!res.ok && res.conflicts?.length) {
        setFolderMergePrompt({
          paths,
          message: res.message,
          conflicts: res.conflicts,
        })
        setStatus(res.message)
        return
      }
      setThumbnailVersion((version) => version + 1)
      setStatus(res.message)
      await reloadAfterFolderMerge(paths[0], res.deleted_sources ?? [])
    } catch (e) {
      setStatus(`合併資料夾失敗：${e}`)
    } finally {
      setLoading(false)
    }
  }

  const promptCreateFolder = async (parent: string) => {
    const name = await promptText({ title: '新資料夾名稱：' })
    if (!name) return
    const res = await api.createFolder(parent, name)
    setStatus(res.message)
    await refreshTree()
    await loadFolder(selectedTreePaths.length ? selectedTreePaths : [parent])
  }

  const promptEditTags = async (paths: string[], currentTags: string[]) => {
    const uniquePaths = Array.from(new Set(paths)).filter(Boolean)
    if (!uniquePaths.length) return
    const raw = await promptText({
      title: '編輯標籤',
      description: '以逗號分隔，留空可清除全部',
      defaultValue: currentTags.join(', '),
    })
    if (raw === null) return
    const tags = raw.split(',').map((t) => t.trim()).filter(Boolean)
    const res = await api.setTags(uniquePaths, tags)
    setStatus(res.message)
    await loadTags()
    await reloadCurrentPreview()
  }

  const promptAddTags = async (paths: string[]) => {
    const uniquePaths = Array.from(new Set(paths)).filter(Boolean)
    if (!uniquePaths.length) return
    const raw = await promptText({
      title: '添加標籤',
      description: '輸入標籤（以逗號分隔）',
      placeholder: '例如：精選, 2024',
    })
    if (!raw) return
    const tags = raw.split(',').map((t) => t.trim()).filter(Boolean)
    const res = await api.addTags(uniquePaths, tags)
    setStatus(res.message)
    await loadTags()
    await reloadCurrentPreview()
  }

  const confirmDeleteTags = async (tags: string[]) => {
    const uniqueTags = Array.from(new Set(tags)).filter(Boolean)
    if (!uniqueTags.length) return
    if (deletingTags.size > 0) {
      setStatus('正在刪除中，請等候…')
      return
    }
    const label = uniqueTags.length === 1 ? `「${uniqueTags[0]}」` : `${uniqueTags.length} 個已選取標籤`
    if (!(await confirmAction(`確定要刪除${label}？此動作會從所有媒體檔移除這些標籤。`))) return

    const removing = new Set(uniqueTags.map((tag) => foldCase(tag)))
    const previousAllTags = allTags
    const previousFilter = filter
    setDeletingTags(removing)
    setAllTags((current) => current.filter((tag) => !removing.has(foldCase(tag))))
    setFilter((current) => ({
      ...current,
      selected_tags: current.selected_tags.filter((tag) => !removing.has(foldCase(tag))),
    }))
    setStatus('正在刪除標籤…')

    try {
      const res = await api.deleteTags(uniqueTags)
      setAllTags(res.all_tags)
      setFilter(res.filter_state)
      await refreshTree()
      await reloadCurrentPreview()
      setStatus(`已刪除 ${uniqueTags.length} 個標籤`)
    } catch (e) {
      setAllTags(previousAllTags)
      setFilter(previousFilter)
      setStatus(`刪除標籤失敗：${e}`)
    } finally {
      setDeletingTags(new Set())
    }
  }

  const promptRenameFolder = async (path: string, current: string) => {
    const name = await promptText({ title: '新資料夾名稱：', defaultValue: current })
    if (!name || name === current) return
    const res = await api.renameFolder(path, name)
    setThumbnailVersion((version) => version + 1)
    setStatus(res.message)
    await refreshTree()
    await loadFolder(selectedTreePaths)
  }

  const promptRenameFile = async (path: string) => {
    const base = path.split(/[/\\]/).pop() ?? ''
    const stem = base.replace(/\.[^.]+$/, '')
    const name = await promptText({ title: '新主檔名：', defaultValue: stem })
    if (!name) return
    const res = await api.renameFile(path, name)
    setThumbnailVersion((version) => version + 1)
    setStatus(res.message)
    await reloadCurrentPreview()
  }

  const promptRenameNumbered = async (paths: string[]) => {
    if (!paths.length) return
    const base = await promptText({ title: '命名規則（例如 ABC）：' })
    if (!base) return
    const startRaw = await promptText({ title: '起始序號：', defaultValue: '1' })
    if (!startRaw) return
    const startNo = parseInt(startRaw, 10)
    if (!Number.isFinite(startNo)) {
      setStatus('起始序號必須是數字')
      return
    }

    const renamingFolders = paths.every((path) => entries.some((entry) => entry.path === path))
    const orderBeforeRename = renamingFolders ? entries.map((item) => item.id) : media.map((item) => item.id)
    const res = await api.renameNumbered(paths, base, startNo, renamingFolders)
    setThumbnailVersion((version) => version + 1)
    if (filter.sort_mode === 'manual') {
      const renamedIds = res.renamed_paths?.length
        ? res.renamed_paths
        : buildFallbackRenamedIds(paths, base, startNo, renamingFolders)
      const renameMap = new Map(paths.map((oldId, index) => [oldId, renamedIds[index] ?? oldId]))
      if (viewMode === 'media') {
        const scope = getTagFilterScopePaths()
        const preview = scope.length ? await loadTaggedMedia(scope) : null
        if (preview) {
          const reordered = reorderRenamedItems(preview.items, orderBeforeRename, renameMap, (item) => item.name)
          setMedia(reordered)
          await api.reorder(preview.scope_path, 'media', reordered.map((item) => item.id))
          setStatus(`${res.message}，已依序號更新手動排序`)
          return
        }
      } else if (selectedTreePaths.length) {
        const preview = await loadFolder(selectedTreePaths)
        if (preview) {
          if (renamingFolders) {
            const reordered = reorderRenamedItems(
              preview.entries,
              orderBeforeRename,
              renameMap,
              (item) => item.subfolder_name,
            )
            setEntries(reordered)
            await api.reorder(preview.scope_path, 'entries', reordered.map((item) => item.id))
          } else {
            const reordered = reorderRenamedItems(preview.media, orderBeforeRename, renameMap, (item) => item.name)
            setMedia(reordered)
            await api.reorder(preview.scope_path, 'media', reordered.map((item) => item.id))
          }
          setStatus(`${res.message}，已依序號更新手動排序`)
          return
        }
      }
    }
    setStatus(res.message)
    await reloadCurrentPreview()
  }

  const promptTransfer = async (paths: string[]) => {
    let target = ''
    if (isTauriRuntime()) {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        directory: true,
        multiple: false,
        title: '選擇轉移目標資料夾',
        defaultPath: selectedTreePaths[0] || config.root_folder || undefined,
      })
      if (!selected || Array.isArray(selected)) return
      target = selected
    } else {
      target = (await promptText({
        title: '目標資料夾完整路徑：',
        defaultValue: selectedTreePaths[0] || config.root_folder,
      })) ?? ''
    }
    target = normalizeFolderPath(target)
    if (!target) return
    const res = await api.transfer(paths, target)
    setThumbnailVersion((version) => version + 1)
    setStatus(res.message)
    await refreshTree()
    await reloadCurrentPreview()
    setSelectedIds(new Set())
  }

  const confirmDeleteFolder = async (path: string) => {
    if (!(await confirmAction('確定刪除此資料夾及其所有內容？'))) return
    const res = await api.deleteFolder(path)
    setThumbnailVersion((version) => version + 1)
    setStatus(res.message)
    await refreshTree()
    if (config.root_folder) await loadFolder(config.root_folder)
  }

  const confirmDeleteFiles = async (paths: string[]) => {
    if (!(await confirmAction(`確定刪除 ${paths.length} 個檔案？`))) return
    const deletedPaths = new Set(paths.map(normalizeId))
    setMedia((current) => {
      const next = current.filter((item) => !deletedPaths.has(normalizeId(item.path)))
      setLightboxIndex((idx) => {
        if (idx === null) return null
        if (!next.length) return null
        return Math.min(idx, next.length - 1)
      })
      return next
    })
    const res = await api.deleteFiles(paths)
    setThumbnailVersion((version) => version + 1)
    setStatus(res.message)
    await reloadCurrentPreview()
    setSelectedIds(new Set())
  }

  const chooseFolder = async () => {
    let path = ''
    try {
      if (isTauriRuntime()) {
        const { open } = await import('@tauri-apps/plugin-dialog')
        const selected = await open({
          directory: true,
          multiple: false,
          title: '選擇主資料夾',
          defaultPath: config.root_folder || undefined,
        })
        if (!selected || Array.isArray(selected)) return
        path = selected
      } else {
        path = (await promptText({
          title: '主資料夾完整路徑：',
          defaultValue: config.root_folder,
        })) ?? ''
      }
      path = normalizeFolderPath(path)
      if (!path) return

      setStatus('正在設定主資料夾…')
      const res = await api.setRoot(path)
      const cfg = await api.getConfig()
      const rootPath = cfg.root_folder || path
      setConfig({ root_folder: rootPath, has_root: true })
      setStatus(res.message)
      await loadTags()
      await refreshTree()
      setSelectedTreePaths([rootPath])
      setSelectedTreeTypes({ [rootPath]: 'root' })
      await loadFolder(rootPath)
    } catch (e) {
      setStatus(`設定主資料夾失敗：${e}`)
    }
  }

  const handleImportTags = () => fileInputRef.current?.click()

  const onImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const content = await file.text()
    const format = file.name.endsWith('.csv') ? 'csv' : 'json'
    const res = await api.importTags(content, format, true)
    setStatus(res.message)
    await loadTags()
    await refreshTree()
    e.target.value = ''
  }

  const handleExportTags = async () => {
    const format = (await confirmAction('確定匯出 JSON？（取消則匯出 CSV）')) ? 'json' : 'csv'
    const content = await api.exportTags(format)
    const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `media_tags.${format}`
    a.click()
    setStatus(`已匯出 ${format.toUpperCase()} 標籤`)
  }

  const visibleItems = getGridItems(viewMode, entries, media)
  const selectedPaths = visibleItems.filter((item) => selectedIds.has(item.id)).map((item) => item.path)
  const entryPathSet = useMemo(() => new Set(entries.map((entry) => normalizeId(entry.path))), [entries])
  const selectedHasMedia = selectedPaths.some((path) => !entryPathSet.has(normalizeId(path)))
  const treeFocusPath = selectedTreePaths.length === 1 ? selectedTreePaths[0] : undefined

  return (
    <div className="h-full flex flex-col min-h-0">
      {!isDesktopApp() && !webBannerDismissed ? (
        <WebLimitedBanner onDismiss={() => setWebBannerDismissed(true)} />
      ) : null}
      <div className="flex-1 flex flex-col min-h-0">
      <input ref={fileInputRef} type="file" accept=".json,.csv" className="hidden" onChange={onImportFile} />
      <AppShell
        sidebar={
          <SidebarTree
            nodes={tree}
            selectedPaths={selectedTreePaths}
            focusPath={treeFocusPath}
            initializing={initializing}
            prunePaths={sidebarPrunePaths}
            treeRevision={treeRevision}
            onSelect={handleTreeSelect}
            onContextMenu={(e, paths) => {
              setContextMenu(null)
              setTagContextMenu(null)
              if (paths.length < 2) {
                setSidebarContextMenu(null)
                return
              }
              setSidebarContextMenu({ x: e.clientX, y: e.clientY, paths })
            }}
          />
        }
        breadcrumb={breadcrumb}
        scopeLabel={scopeLabel}
        status={loading ? `${status} · 載入中…` : status}
        rootFolder={config.root_folder}
        sidebarOpen={sidebarOpen}
        darkMode={darkMode}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        onToggleTheme={() => applyTheme(!darkMode)}
        onNavigate={handleNavigate}
        onChooseFolder={chooseFolder}
        onRefresh={async () => {
          await api.invalidateTagCache()
          await refreshTree()
          await loadTags()
          await reloadCurrentPreview()
          setStatus('已刷新')
        }}
        onImportTags={handleImportTags}
        onExportTags={handleExportTags}
        platformLabel={getPlatformLabel()}
      >
        <TagFilterBar
          allTags={allTags}
          filter={filter}
          expanded={tagsExpanded}
          deletingTags={deletingTags}
          onToggleExpand={() => setTagsExpanded((v) => !v)}
          onToggleTag={toggleTag}
          onContextMenu={(e, tag) => {
            setContextMenu(null)
            setSidebarContextMenu(null)
            setTagContextMenu({ x: e.clientX, y: e.clientY, tag })
          }}
        />
        <MediaFilterBar
          filter={filter}
          viewMode={viewMode}
          onChange={(patch) => updateFilter(patch)}
          onApplyDuration={() => updateFilter({})}
        />
        <PreviewGrid
          viewMode={viewMode}
          entries={entries}
          media={media}
          selectedIds={selectedIds}
          loading={loading}
          initializing={initializing}
          thumbnailVersion={thumbnailVersion}
          sortable
          onSelect={handleSelect}
          onDoubleClickEntry={handleDoubleClickEntry}
          onDoubleClickMedia={(_item, index) => setLightboxIndex(index)}
          onContextMenu={(e, id) => {
            e.preventDefault()
            setSidebarContextMenu(null)
            setTagContextMenu(null)
            setContextMenu({ x: e.clientX, y: e.clientY, targetId: id })
          }}
          onReorder={async (fromId, toId, position) => {
            const entryIds = new Set(entries.map((entry) => entry.id))
            const fromIsEntry = entryIds.has(fromId)
            const toIsEntry = entryIds.has(toId)
            if (fromIsEntry !== toIsEntry) return
            const items = fromIsEntry ? entries : media
            const reorderKind = fromIsEntry ? 'entries' : 'media'
            const ids = items.map((it) => it.id)
            const fromIdx = ids.indexOf(fromId)
            const toIdx = ids.indexOf(toId)
            if (fromIdx < 0 || toIdx < 0) return
            const movingIds =
              selectedIds.has(fromId) && selectedIds.size > 1
                ? ids.filter((id) => selectedIds.has(id))
                : [fromId]
            if (movingIds.includes(toId)) return
            const withoutMoving = ids.filter((id) => !movingIds.includes(id))
            const targetIdx = withoutMoving.indexOf(toId)
            if (targetIdx < 0) return
            const next = [...withoutMoving]
            next.splice(position === 'after' ? targetIdx + 1 : targetIdx, 0, ...movingIds)
            const orderIndex = new Map(next.map((id, index) => [id, index]))
            if (fromIsEntry) {
              setEntries((current) =>
                [...current].sort((a, b) => (orderIndex.get(a.id) ?? 0) - (orderIndex.get(b.id) ?? 0)),
              )
            } else {
              setMedia((current) =>
                [...current].sort((a, b) => (orderIndex.get(a.id) ?? 0) - (orderIndex.get(b.id) ?? 0)),
              )
            }
            setFilter((current) => ({ ...current, sort_mode: 'manual' }))
            try {
              await api.reorder(scopePath, reorderKind, next)
            } catch (e) {
              setStatus(`已更新畫面排序，但暫存排序失敗：${e}`)
              return
            }
            setStatus('已更新手動排序')
          }}
        />
      </AppShell>

      <SelectionToolbar
        count={selectedIds.size}
        showAddTags={viewMode === 'media' || selectedHasMedia}
        onTransfer={() => promptTransfer(selectedPaths)}
        onRenameNumbered={() => promptRenameNumbered(selectedPaths)}
        onAddTags={() => promptAddTags(selectedPaths)}
        onDelete={() => {
          const filePaths = selectedPaths.filter((path) => media.some((item) => item.path === path))
          const folderPaths = selectedPaths.filter((path) => entries.some((item) => item.path === path))
          if (filePaths.length) void confirmDeleteFiles(filePaths)
          folderPaths.forEach((path) => {
            void confirmDeleteFolder(path)
          })
        }}
      />

      {lightboxIndex !== null && (
        <MediaLightbox
          items={media}
          initialIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onStatus={setStatus}
          onFrameSaved={async (message) => {
            setThumbnailVersion((version) => version + 1)
            await refreshTree()
            await reloadCurrentPreview()
            setStatus(message)
          }}
        />
      )}

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={getContextItems(contextMenu.targetId)}
          onClose={() => setContextMenu(null)}
        />
      )}

      {sidebarContextMenu && (
        <ContextMenu
          x={sidebarContextMenu.x}
          y={sidebarContextMenu.y}
          items={getSidebarContextItems(sidebarContextMenu.paths)}
          onClose={() => setSidebarContextMenu(null)}
        />
      )}

      {tagContextMenu && (
        <ContextMenu
          x={tagContextMenu.x}
          y={tagContextMenu.y}
          items={getTagContextItems(tagContextMenu.tag)}
          onClose={() => setTagContextMenu(null)}
        />
      )}

      {folderMergePrompt && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-[460px] rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-panel)] p-5 shadow-[var(--shadow-md)]">
            <h2 className="text-base font-semibold text-[var(--color-text)]">合併資料夾發現同名項目</h2>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">{folderMergePrompt.message}</p>
            <div className="mt-3 max-h-36 overflow-y-auto rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel-2)] p-2 text-xs text-[var(--color-text-muted)]">
              {folderMergePrompt.conflicts.slice(0, 8).map((conflict) => (
                <div key={`${conflict.source_path}-${conflict.target_path}`} className="truncate">
                  {conflict.name}
                </div>
              ))}
              {folderMergePrompt.conflicts.length > 8 && (
                <div>另有 {folderMergePrompt.conflicts.length - 8} 個同名項目…</div>
              )}
            </div>
            <p className="mt-3 text-xs text-[var(--color-text-muted)]">
              「保留」會自動改名後合併；「略過」會保留同名項目在原資料夾，該來源資料夾不會刪除。
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => runFolderMerge(folderMergePrompt.paths, 'keep')}
              >
                保留
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => runFolderMerge(folderMergePrompt.paths, 'skip')}
              >
                略過
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setFolderMergePrompt(null)
                  setStatus('已取消資料夾合併')
                }}
              >
                取消
              </Button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
