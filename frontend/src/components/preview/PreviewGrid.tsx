import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef, useMemo, useState } from 'react'
import type { EntryItem, MediaItem, ViewMode } from '../../api/types'
import { EntryCard } from './EntryCard'
import { MediaCard } from './MediaCard'
import { isTauriRuntime, startNativeFileDrag } from '../../lib/nativeDrag'

const CARD_WIDTH = 220
const CARD_GAP = 16
const ENTRY_HEIGHT = 324
const MEDIA_HEIGHT = 304

interface PreviewGridProps {
  viewMode: ViewMode
  entries: EntryItem[]
  media: MediaItem[]
  selectedIds: Set<string>
  sortable?: boolean
  onSelect: (id: string, e: React.MouseEvent, index: number) => void
  onDoubleClickEntry: (item: EntryItem) => void
  onDoubleClickMedia: (item: MediaItem, index: number) => void
  onContextMenu: (e: React.MouseEvent, id: string) => void
  onReorder?: (fromId: string, toId: string, position: 'before' | 'after') => void
}

export function PreviewGrid({
  viewMode,
  entries,
  media,
  selectedIds,
  onSelect,
  onDoubleClickEntry,
  onDoubleClickMedia,
  onContextMenu,
  sortable,
  onReorder,
}: PreviewGridProps) {
  const [dragId, setDragId] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<{ id: string; position: 'before' | 'after' } | null>(null)
  const [dropIndicator, setDropIndicator] = useState<{ left: number; top: number; height: number } | null>(null)
  const parentRef = useRef<HTMLDivElement>(null)
  const items = viewMode === 'entries' ? entries : media
  const rowHeight = viewMode === 'entries' ? ENTRY_HEIGHT : MEDIA_HEIGHT
  const isDraggingSelectedGroup = dragId !== null && selectedIds.has(dragId) && selectedIds.size > 1
  const nativeFileDragEnabled = isTauriRuntime()

  const columnCount = useMemo(() => {
    const w = parentRef.current?.clientWidth ?? 800
    return Math.max(1, Math.floor((w + CARD_GAP) / (CARD_WIDTH + CARD_GAP)))
  }, [items.length, viewMode])

  const rowCount = Math.ceil(items.length / columnCount) || 1

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 2,
  })

  const getDropPosition = (event: React.DragEvent<HTMLElement>): 'before' | 'after' => {
    const rect = event.currentTarget.getBoundingClientRect()
    return event.clientX < rect.left + rect.width / 2 ? 'before' : 'after'
  }

  const updateDropTarget = (event: React.DragEvent<HTMLElement>, id: string) => {
    const isDraggingGroupMember = isDraggingSelectedGroup && selectedIds.has(id)
    if (!sortable || !dragId || dragId === id || isDraggingGroupMember) {
      setDropTarget(null)
      setDropIndicator(null)
      return
    }
    const position = getDropPosition(event)
    const rect = event.currentTarget.getBoundingClientRect()
    setDropTarget({ id, position })
    setDropIndicator({
      left: position === 'before' ? rect.left - CARD_GAP / 2 : rect.right + CARD_GAP / 2,
      top: rect.top + 8,
      height: Math.max(24, rect.height - 16),
    })
  }

  const commitDrop = (event: React.DragEvent<HTMLElement>, id: string) => {
    const isDraggingGroupMember = isDraggingSelectedGroup && selectedIds.has(id)
    if (dragId && dragId !== id && !isDraggingGroupMember) {
      onReorder?.(dragId, id, dropTarget?.id === id ? dropTarget.position : getDropPosition(event))
    }
    setDragId(null)
    setDropTarget(null)
    setDropIndicator(null)
  }

  const setDragPreview = (event: React.DragEvent<HTMLElement>, id: string) => {
    const isGroup = selectedIds.has(id) && selectedIds.size > 1
    if (!isGroup) return

    const preview = document.createElement('div')
    preview.style.position = 'fixed'
    preview.style.top = '-1000px'
    preview.style.left = '-1000px'
    preview.style.width = '176px'
    preview.style.height = '116px'
    preview.style.pointerEvents = 'none'
    preview.style.zIndex = '9999'
    preview.innerHTML = `
      <div style="
        position:absolute; inset:18px 0 0 18px;
        border-radius:14px; background:rgba(79,70,229,.18);
        border:1px solid rgba(79,70,229,.35);
        box-shadow:0 12px 28px rgba(15,23,42,.18);
      "></div>
      <div style="
        position:absolute; inset:9px 9px 9px 9px;
        border-radius:14px; background:rgba(255,255,255,.94);
        border:1px solid rgba(79,70,229,.45);
        box-shadow:0 14px 32px rgba(15,23,42,.22);
        display:flex; align-items:center; justify-content:center;
        font:600 14px -apple-system, Segoe UI, system-ui, sans-serif;
        color:#4f46e5;
      ">
        拖曳 ${selectedIds.size} 項
      </div>
    `
    document.body.appendChild(preview)
    event.dataTransfer.setDragImage(preview, 88, 58)
    window.setTimeout(() => preview.remove(), 0)
  }

  const getNativeDragPaths = (item: MediaItem) => {
    if (selectedIds.has(item.id) && selectedIds.size > 1) {
      return media.filter((candidate) => selectedIds.has(candidate.id)).map((candidate) => candidate.path)
    }
    return [item.path]
  }

  const handleNativeFileDragStart = async (event: React.DragEvent<HTMLElement>, paths: string[]) => {
    event.preventDefault()
    event.stopPropagation()
    setDragId(null)
    setDropTarget(null)
    setDropIndicator(null)

    try {
      await startNativeFileDrag(paths)
    } catch (error) {
      console.error('Failed to start native file drag', error)
    }
  }

  if (!items.length) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-text-muted)] text-sm">
        {viewMode === 'entries' ? '沒有可預覽的子資料夾' : '沒有可預覽的媒體'}
      </div>
    )
  }

  return (
    <div
      ref={parentRef}
      className="relative flex-1 overflow-y-auto px-5 py-5"
      onDragEnd={() => {
        setDragId(null)
        setDropTarget(null)
        setDropIndicator(null)
      }}
    >
      {dropIndicator && (
        <div
          className="pointer-events-none fixed z-50 w-1.5 -translate-x-1/2 rounded-full bg-[var(--color-accent)] shadow-[0_0_0_3px_var(--color-accent-soft)]"
          style={{
            left: dropIndicator.left,
            top: dropIndicator.top,
            height: dropIndicator.height,
          }}
        />
      )}
      <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative', width: '100%' }}>
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const startIdx = virtualRow.index * columnCount
          const rowItems = items.slice(startIdx, startIdx + columnCount)
          return (
            <div
              key={virtualRow.key}
              className="absolute left-0 w-full grid gap-4 px-1 py-2 overflow-visible"
              style={{
                top: virtualRow.start,
                height: virtualRow.size,
                gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))`,
              }}
            >
              {rowItems.map((item, colIdx) => {
                const idx = startIdx + colIdx
                if (viewMode === 'entries') {
                  const entry = item as EntryItem
                  return (
                    <EntryCard
                      key={entry.id}
                      item={entry}
                      selected={selectedIds.has(entry.id)}
                      sortable={sortable}
                      dragging={isDraggingSelectedGroup ? selectedIds.has(entry.id) : dragId === entry.id}
                      dropPosition={null}
                      onDragStart={(e) => {
                        setDragId(entry.id)
                        setDropTarget(null)
                        setDragPreview(e, entry.id)
                      }}
                      onDragOverItem={(e) => updateDropTarget(e, entry.id)}
                      onDragLeave={() => {
                        setDropTarget((current) => (current?.id === entry.id ? null : current))
                      }}
                      onDrop={(e) => commitDrop(e, entry.id)}
                      onSelect={(e) => {
                        if (e.ctrlKey || e.metaKey || e.shiftKey) {
                          onSelect(entry.id, e, idx)
                          return
                        }
                        onDoubleClickEntry(entry)
                      }}
                      onSelectToggle={(e) => onSelect(entry.id, e, idx)}
                      onDoubleClick={() => onDoubleClickEntry(entry)}
                      onContextMenu={(e) => onContextMenu(e, entry.id)}
                    />
                  )
                }
                const mediaItem = item as MediaItem
                return (
                  <MediaCard
                    key={mediaItem.id}
                    item={mediaItem}
                    selected={selectedIds.has(mediaItem.id)}
                    sortable={sortable}
                    dragging={isDraggingSelectedGroup ? selectedIds.has(mediaItem.id) : dragId === mediaItem.id}
                    dropPosition={null}
                    nativeDragPaths={nativeFileDragEnabled ? getNativeDragPaths(mediaItem) : undefined}
                    onNativeFileDragStart={handleNativeFileDragStart}
                    onDragStart={(e) => {
                      setDragId(mediaItem.id)
                      setDropTarget(null)
                      setDragPreview(e, mediaItem.id)
                    }}
                    onDragOverItem={(e) => updateDropTarget(e, mediaItem.id)}
                    onDragLeave={() => {
                      setDropTarget((current) => (current?.id === mediaItem.id ? null : current))
                    }}
                    onDrop={(e) => commitDrop(e, mediaItem.id)}
                    onSelect={(e) => onSelect(mediaItem.id, e, idx)}
                    onDoubleClick={() => onDoubleClickMedia(mediaItem, idx)}
                    onContextMenu={(e) => onContextMenu(e, mediaItem.id)}
                  />
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}
