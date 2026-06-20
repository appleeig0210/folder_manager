import { ChevronDown, ChevronRight, Folder, FolderOpen, User } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { TreeNode } from '../../api/types'
import { api } from '../../api/client'
import { cn } from '../../lib/utils'

interface SidebarTreeProps {
  nodes: TreeNode[]
  selectedPaths: string[]
  initializing?: boolean
  onSelect: (paths: string[], node: TreeNode) => void
  onContextMenu?: (e: React.MouseEvent, paths: string[], node: TreeNode) => void
  onExpandLoaded?: () => void
  prunePaths?: string[]
  treeRevision?: number
}

function TreeItem({
  node,
  depth,
  selectedPaths,
  openPaths,
  childrenByPath,
  onSelect,
  onContextMenu,
  onToggleOpen,
  onExpandLoaded,
}: {
  node: TreeNode
  depth: number
  selectedPaths: string[]
  openPaths: Set<string>
  childrenByPath: Record<string, TreeNode[]>
  onSelect: (node: TreeNode, e: React.MouseEvent) => void
  onContextMenu?: (node: TreeNode, e: React.MouseEvent) => void
  onToggleOpen: (node: TreeNode, children: TreeNode[]) => void
  onExpandLoaded?: () => void
}) {
  const open = openPaths.has(node.path)
  const children = childrenByPath[node.path] ?? node.children
  const [loading, setLoading] = useState(false)
  const hasChildren = node.type !== 'stub' && (children.length > 0 || node.type !== 'subfolder' || children.some((c) => c.type === 'stub'))
  const isSelected = selectedPaths.includes(node.path)
  const isStub = node.type === 'stub'

  if (isStub) return null

  const Icon = node.type === 'person' ? User : node.type === 'root' ? FolderOpen : Folder

  const toggle = async () => {
    if (!open && children.some((c) => c.type === 'stub')) {
      setLoading(true)
      try {
        const loaded = await api.expandNode(node.path)
        onToggleOpen(node, loaded)
        onExpandLoaded?.()
      } finally {
        setLoading(false)
      }
      return
    }
    onToggleOpen(node, children)
  }

  const handleClick = (e: React.MouseEvent) => {
    onSelect(node, e)
  }

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        onContextMenu={(e) => onContextMenu?.(node, e)}
        className={cn(
          'w-full flex items-center gap-1.5 py-1.5 pr-2 rounded-[var(--radius-sm)] text-left text-sm transition-colors outline-none focus:outline-none focus-visible:outline-none',
          isSelected
            ? 'bg-[var(--color-accent-soft)] text-[var(--color-accent)] font-medium'
            : 'text-[var(--color-text)] hover:bg-[var(--color-panel-2)]',
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <span
          className="w-4 h-4 flex items-center justify-center shrink-0 text-[var(--color-text-muted)]"
          onClick={(e) => {
            e.stopPropagation()
            if (hasChildren || node.type !== 'subfolder') toggle()
          }}
        >
          {hasChildren || node.type !== 'subfolder' ? (
            loading ? (
              <span className="w-3 h-3 border-2 border-[var(--color-border)] border-t-[var(--color-accent)] rounded-full animate-spin" />
            ) : open ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )
          ) : null}
        </span>
        <Icon className="w-4 h-4 shrink-0 opacity-70" />
        <span className="truncate">{node.name}</span>
      </button>
      {open &&
        children
          .filter((c) => c.type !== 'stub')
          .map((child) => (
            <TreeItem
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedPaths={selectedPaths}
              openPaths={openPaths}
              childrenByPath={childrenByPath}
              onSelect={onSelect}
              onContextMenu={onContextMenu}
              onToggleOpen={onToggleOpen}
              onExpandLoaded={onExpandLoaded}
            />
          ))}
    </div>
  )
}

function buildInitialChildrenByPath(nodes: TreeNode[]): Record<string, TreeNode[]> {
  const result: Record<string, TreeNode[]> = {}
  const visit = (node: TreeNode) => {
    result[node.path] = node.children
    node.children.forEach(visit)
  }
  nodes.forEach(visit)
  return result
}

function collectTreePaths(nodes: TreeNode[]): Set<string> {
  const paths = new Set<string>()
  const visit = (node: TreeNode) => {
    if (node.type === 'stub') return
    paths.add(node.path)
    node.children.forEach(visit)
  }
  nodes.forEach(visit)
  return paths
}

function normalizeTreePath(path: string): string {
  return path.replaceAll('\\', '/').replace(/\/+$/, '')
}

function applyPrunePaths(
  childrenByPath: Record<string, TreeNode[]>,
  prunePaths: string[] | undefined,
): Record<string, TreeNode[]> {
  if (!prunePaths?.length) return childrenByPath
  const removed = new Set(prunePaths.map(normalizeTreePath))
  const next: Record<string, TreeNode[]> = {}
  for (const [path, children] of Object.entries(childrenByPath)) {
    next[path] = children.filter(
      (child) => child.type === 'stub' || !removed.has(normalizeTreePath(child.path)),
    )
  }
  return next
}

function syncChildrenByPath(
  current: Record<string, TreeNode[]>,
  nodes: TreeNode[],
): Record<string, TreeNode[]> {
  const fromApi = buildInitialChildrenByPath(nodes)
  const next: Record<string, TreeNode[]> = { ...fromApi }

  // Keep lazy-expanded subtrees only for paths not present in the fresh API snapshot.
  for (const [path, cached] of Object.entries(current)) {
    if (path in fromApi) continue
    if (cached.some((child) => child.type !== 'stub')) {
      next[path] = cached
    }
  }

  return next
}

function flattenVisibleNodes(
  nodes: TreeNode[],
  openPaths: Set<string>,
  childrenByPath: Record<string, TreeNode[]>,
): TreeNode[] {
  const result: TreeNode[] = []
  const visit = (node: TreeNode) => {
    if (node.type === 'stub') return
    result.push(node)
    if (!openPaths.has(node.path)) return
    const children = childrenByPath[node.path] ?? node.children
    children.forEach(visit)
  }
  nodes.forEach(visit)
  return result
}

export function SidebarTree({
  nodes,
  selectedPaths,
  initializing = false,
  onSelect,
  onContextMenu,
  onExpandLoaded,
  prunePaths,
  treeRevision = 0,
}: SidebarTreeProps) {
  const [anchorPath, setAnchorPath] = useState<string | null>(null)
  const [openPaths, setOpenPaths] = useState<Set<string>>(() => new Set(nodes.filter((node) => node.type === 'root').map((node) => node.path)))
  const [childrenByPath, setChildrenByPath] = useState<Record<string, TreeNode[]>>(() => buildInitialChildrenByPath(nodes))
  const lastRefreshRevisionRef = useRef(0)

  useEffect(() => {
    const removed = new Set((prunePaths ?? []).map(normalizeTreePath))
    setChildrenByPath((current) =>
      applyPrunePaths(syncChildrenByPath(current, nodes), prunePaths),
    )
    setOpenPaths((current) => {
      const next = new Set<string>()
      for (const path of current) {
        if (removed.has(normalizeTreePath(path))) continue
        next.add(path)
      }
      nodes.filter((node) => node.type === 'root').forEach((node) => next.add(node.path))
      return next
    })
  }, [nodes, prunePaths])

  useEffect(() => {
    if (treeRevision === 0) return
    if (lastRefreshRevisionRef.current === treeRevision) return
    lastRefreshRevisionRef.current = treeRevision

    let cancelled = false
    void (async () => {
      const freshPaths = collectTreePaths(nodes)
      const targets = [...openPaths].filter((path) => freshPaths.has(path))
      for (const path of targets) {
        try {
          const loaded = await api.expandNode(path)
          if (cancelled) return
          setChildrenByPath((current) => applyPrunePaths({ ...current, [path]: loaded }, prunePaths))
        } catch {
          // Ignore removed paths.
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [nodes, openPaths, prunePaths, treeRevision])

  const visibleNodes = useMemo(
    () => flattenVisibleNodes(nodes, openPaths, childrenByPath),
    [childrenByPath, nodes, openPaths],
  )

  const handleToggleOpen = (node: TreeNode, children: TreeNode[]) => {
    setChildrenByPath((current) => ({ ...current, [node.path]: children }))
    setOpenPaths((current) => {
      const next = new Set(current)
      if (next.has(node.path)) next.delete(node.path)
      else next.add(node.path)
      return next
    })
  }

  const handleSelect = (node: TreeNode, e: React.MouseEvent) => {
    if (e.shiftKey && anchorPath) {
      const anchorIndex = visibleNodes.findIndex((candidate) => candidate.path === anchorPath)
      const currentIndex = visibleNodes.findIndex((candidate) => candidate.path === node.path)
      if (anchorIndex >= 0 && currentIndex >= 0) {
        const [lo, hi] = [anchorIndex, currentIndex].sort((a, b) => a - b)
        onSelect(visibleNodes.slice(lo, hi + 1).map((candidate) => candidate.path), node)
        return
      }
    }

    if (e.ctrlKey || e.metaKey) {
      setAnchorPath(node.path)
      if (selectedPaths.includes(node.path)) {
        onSelect(selectedPaths.filter((p) => p !== node.path), node)
      } else {
        onSelect([...selectedPaths, node.path], node)
      }
      return
    }

    setAnchorPath(node.path)
    onSelect([node.path], node)
  }

  const handleContextMenu = (node: TreeNode, e: React.MouseEvent) => {
    e.preventDefault()
    const selectedSet = new Set(selectedPaths)
    const paths = selectedSet.has(node.path)
      ? visibleNodes.filter((candidate) => selectedSet.has(candidate.path)).map((candidate) => candidate.path)
      : [node.path]

    if (!selectedSet.has(node.path)) {
      setAnchorPath(node.path)
      onSelect([node.path], node)
    }

    onContextMenu?.(e, paths, node)
  }

  return (
    <div className="flex flex-col gap-0.5 p-2 overflow-y-auto h-full">
      {initializing && nodes.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-8 text-[var(--color-text-muted)] text-sm">
          <span className="w-4 h-4 border-2 border-[var(--color-border)] border-t-[var(--color-accent)] rounded-full animate-spin" />
          載入中，請稍後…
        </div>
      ) : null}
      {nodes.map((node) => (
        <TreeItem
          key={node.id}
          node={node}
          depth={0}
          selectedPaths={selectedPaths}
          openPaths={openPaths}
          childrenByPath={childrenByPath}
          onSelect={handleSelect}
          onContextMenu={handleContextMenu}
          onToggleOpen={handleToggleOpen}
          onExpandLoaded={onExpandLoaded}
        />
      ))}
    </div>
  )
}
