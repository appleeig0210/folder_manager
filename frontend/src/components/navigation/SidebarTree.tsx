import { ChevronDown, ChevronRight, Folder, FolderOpen, User } from 'lucide-react'
import { useState } from 'react'
import type { TreeNode } from '../../api/types'
import { api } from '../../api/client'
import { cn } from '../../lib/utils'

interface SidebarTreeProps {
  nodes: TreeNode[]
  selectedPaths: string[]
  onSelect: (paths: string[], node: TreeNode) => void
  onExpandLoaded?: () => void
}

function TreeItem({
  node,
  depth,
  selectedPaths,
  onSelect,
  onExpandLoaded,
}: {
  node: TreeNode
  depth: number
  selectedPaths: string[]
  onSelect: (paths: string[], node: TreeNode) => void
  onExpandLoaded?: () => void
}) {
  const [open, setOpen] = useState(depth === 0)
  const [children, setChildren] = useState<TreeNode[]>(node.children)
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
        setChildren(loaded)
        onExpandLoaded?.()
      } finally {
        setLoading(false)
      }
    }
    setOpen(!open)
  }

  const handleClick = (e: React.MouseEvent) => {
    if (e.shiftKey && selectedPaths.length) {
      onSelect([...new Set([...selectedPaths, node.path])], node)
      return
    }
    if (e.ctrlKey || e.metaKey) {
      if (isSelected) {
        onSelect(selectedPaths.filter((p) => p !== node.path), node)
      } else {
        onSelect([...selectedPaths, node.path], node)
      }
      return
    }
    onSelect([node.path], node)
  }

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
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
              onSelect={onSelect}
              onExpandLoaded={onExpandLoaded}
            />
          ))}
    </div>
  )
}

export function SidebarTree({ nodes, selectedPaths, onSelect, onExpandLoaded }: SidebarTreeProps) {
  return (
    <div className="flex flex-col gap-0.5 p-2 overflow-y-auto h-full">
      {nodes.map((node) => (
        <TreeItem
          key={node.id}
          node={node}
          depth={0}
          selectedPaths={selectedPaths}
          onSelect={onSelect}
          onExpandLoaded={onExpandLoaded}
        />
      ))}
    </div>
  )
}
