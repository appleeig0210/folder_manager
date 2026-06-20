import { useVirtualizer } from '@tanstack/react-virtual'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { EntryItem, MediaItem, ViewMode } from '../../api/types'
import { EntryCard } from './EntryCard'
import { MediaCard } from './MediaCard'
import { supportsNativeFileDrag } from '../../lib/platform'
import { startNativeFileDrag } from '../../lib/nativeDrag'

const CARD_WIDTH = 220
const CARD_GAP = 16
const GRID_ROW_HORIZONTAL_PADDING = 8
const DROP_INDICATOR_INSET = 4
const AUTO_SCROLL_EDGE = 72
const AUTO_SCROLL_MAX_STEP = 18
const ENTRY_HEIGHT = 324
const MEDIA_HEIGHT = 304

type GridCell =
  | { kind: 'entry'; item: EntryItem }
  | { kind: 'media'; item: MediaItem }

function buildGridCells(viewMode: ViewMode, entries: EntryItem[], media: MediaItem[]): GridCell[] {
  if (viewMode === 'folder') {
    return [
      ...entries.map((item) => ({ kind: 'entry' as const, item })),
      ...media.map((item) => ({ kind: 'media' as const, item })),
    ]
  }
  if (viewMode === 'entries') {
    return entries.map((item) => ({ kind: 'entry' as const, item }))
  }
  return media.map((item) => ({ kind: 'media' as const, item }))
}

interface PreviewGridProps {
  viewMode: ViewMode
  entries: EntryItem[]
  media: MediaItem[]
  selectedIds: Set<string>
  loading?: boolean
  initializing?: boolean
  thumbnailVersion?: number
  sortable?: boolean
  onSelect: (id: string, e: React.MouseEvent, index: number) => void
  onDoubleClickEntry: (item: EntryItem) => void
  onDoubleClickMedia: (item: MediaItem, index: number) => void
  onContextMenu: (e: React.MouseEvent, id: string) => void
  onReorder?: (fromId: string, toId: string, position: 'before' | 'after') => void
}

function getAutoScrollStep(clientY: number, parent: HTMLDivElement) {
  const rect = parent.getBoundingClientRect()
  const topDistance = clientY - rect.top
  const bottomDistance = rect.bottom - clientY

  if (topDistance < AUTO_SCROLL_EDGE) {
    const intensity = Math.min(1, (AUTO_SCROLL_EDGE - topDistance) / AUTO_SCROLL_EDGE)
    return -Math.max(1, Math.ceil(intensity * AUTO_SCROLL_MAX_STEP))
  }
  if (bottomDistance < AUTO_SCROLL_EDGE) {
    const intensity = Math.min(1, (AUTO_SCROLL_EDGE - bottomDistance) / AUTO_SCROLL_EDGE)
    return Math.max(1, Math.ceil(intensity * AUTO_SCROLL_MAX_STEP))
  }
  return 0
}

export function PreviewGrid({
  viewMode,
  entries,
  media,
  selectedIds,
  loading = false,
  initializing = false,
  thumbnailVersion,
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
  const [containerWidth, setContainerWidth] = useState(0)
  const parentRef = useRef<HTMLDivElement>(null)
  const autoScrollFrameRef = useRef<number | null>(null)
  const dragClientYRef = useRef<number | null>(null)
  const gridCells = useMemo(() => buildGridCells(viewMode, entries, media), [viewMode, entries, media])
  const rowHeight = viewMode === 'media' ? MEDIA_HEIGHT : ENTRY_HEIGHT
  const isDraggingSelectedGroup = dragId !== null && selectedIds.has(dragId) && selectedIds.size > 1
  const nativeFileDragEnabled = supportsNativeFileDrag()
  const listSignature = useMemo(() => gridCells.map((cell) => cell.item.id).join('\0'), [gridCells])

  useLayoutEffect(() => {
    const parent = parentRef.current
    if (!parent) return

    const updateWidth = (width: number) => {
      setContainerWidth(Math.max(0, Math.floor(width - GRID_ROW_HORIZONTAL_PADDING)))
    }

    const parentStyle = window.getComputedStyle(parent)
    updateWidth(
      parent.clientWidth - parseFloat(parentStyle.paddingLeft) - parseFloat(parentStyle.paddingRight),
    )

    const observer = new ResizeObserver(([entry]) => {
      updateWidth(entry.contentRect.width)
    })
    observer.observe(parent)

    return () => observer.disconnect()
  }, [gridCells.length])

  const stopAutoScroll = useCallback(() => {
    if (autoScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(autoScrollFrameRef.current)
      autoScrollFrameRef.current = null
    }
    dragClientYRef.current = null
  }, [])

  const runAutoScroll = useCallback(() => {
    autoScrollFrameRef.current = null

    const parent = parentRef.current
    const clientY = dragClientYRef.current
    if (!parent || clientY === null) return

    const step = getAutoScrollStep(clientY, parent)
    if (step === 0) return

    parent.scrollTop += step
    autoScrollFrameRef.current = window.requestAnimationFrame(runAutoScroll)
  }, [])

  const updateAutoScroll = useCallback((clientY: number) => {
    dragClientYRef.current = clientY
    if (autoScrollFrameRef.current === null) {
      autoScrollFrameRef.current = window.requestAnimationFrame(runAutoScroll)
    }
  }, [runAutoScroll])

  useEffect(() => {
    if (!dragId) {
      stopAutoScroll()
      return
    }

    const handleWindowDragOver = (event: DragEvent) => {
      updateAutoScroll(event.clientY)
    }

    window.addEventListener('dragover', handleWindowDragOver)

    return () => {
      window.removeEventListener('dragover', handleWindowDragOver)
      stopAutoScroll()
    }
  }, [dragId, stopAutoScroll, updateAutoScroll])

  const columnCount = useMemo(() => {
    const w = containerWidth || CARD_WIDTH
    return Math.max(1, Math.floor((w + CARD_GAP) / (CARD_WIDTH + CARD_GAP)))
  }, [containerWidth])

  const rowCount = Math.ceil(gridCells.length / columnCount) || 1

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 2,
  })

  useLayoutEffect(() => {
    rowVirtualizer.measure()
    const parent = parentRef.current
    if (!parent) return
    const maxScrollTop = Math.max(0, rowVirtualizer.getTotalSize() - parent.clientHeight)
    if (parent.scrollTop > maxScrollTop) {
      parent.scrollTop = maxScrollTop
    }
  }, [listSignature, columnCount, rowCount, rowHeight, rowVirtualizer])

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
    updateAutoScroll(event.clientY)
    const position = getDropPosition(event)
    const rect = event.currentTarget.getBoundingClientRect()
    const parentRect = parentRef.current?.getBoundingClientRect()
    const top = parentRect ? Math.max(rect.top + 8, parentRect.top + DROP_INDICATOR_INSET) : rect.top + 8
    const bottom = parentRect ? Math.min(rect.bottom - 8, parentRect.bottom - DROP_INDICATOR_INSET) : rect.bottom - 8
    const height = bottom - top

    setDropTarget({ id, position })
    setDropIndicator(
      height >= 24
        ? {
            left: position === 'before' ? rect.left - CARD_GAP / 2 : rect.right + CARD_GAP / 2,
            top,
            height,
          }
        : null,
    )
  }

  const commitDrop = (event: React.DragEvent<HTMLElement>, id: string) => {
    const isDraggingGroupMember = isDraggingSelectedGroup && selectedIds.has(id)
    if (dragId && dragId !== id && !isDraggingGroupMember) {
      onReorder?.(dragId, id, dropTarget?.id === id ? dropTarget.position : getDropPosition(event))
    }
    setDragId(null)
    setDropTarget(null)
    setDropIndicator(null)
    stopAutoScroll()
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
    stopAutoScroll()

    try {
      await startNativeFileDrag(paths)
    } catch (error) {
      console.error('Failed to start native file drag', error)
    }
  }

  if (!gridCells.length) {
    if (initializing || loading) {
      const message = initializing
        ? '載入中，請稍後…'
        : viewMode === 'media'
          ? '媒體讀取中…'
          : '資料夾內容讀取中…'
      return (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-[var(--color-text-muted)] text-sm">
          <span className="w-5 h-5 border-2 border-[var(--color-border)] border-t-[var(--color-accent)] rounded-full animate-spin" />
          {message}
        </div>
      )
    }
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-text-muted)] text-sm">
        {viewMode === 'media' ? '沒有可預覽的媒體' : '此資料夾是空的'}
      </div>
    )
  }

  return (
    <div
      ref={parentRef}
      className="relative flex-1 overflow-y-auto px-5 pt-3 pb-5"
      onDragOver={(e) => {
        if (!dragId) return
        e.preventDefault()
        updateAutoScroll(e.clientY)
      }}
      onDragEnd={() => {
        setDragId(null)
        setDropTarget(null)
        setDropIndicator(null)
        stopAutoScroll()
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
      <div
        key={listSignature}
        style={{ height: rowVirtualizer.getTotalSize(), position: 'relative', width: '100%' }}
      >
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const startIdx = virtualRow.index * columnCount
          const rowItems = gridCells.slice(startIdx, startIdx + columnCount)
          const rowSignature = rowItems.map((cell) => cell.item.id).join('\0')
          return (
            <div
              key={`${listSignature}:${virtualRow.index}:${rowSignature}`}
              className="absolute left-0 w-full grid gap-4 px-1 py-2 overflow-visible"
              style={{
                top: virtualRow.start,
                height: virtualRow.size,
                gridTemplateColumns: `repeat(${columnCount}, minmax(${CARD_WIDTH}px, 1fr))`,
              }}
            >
              {rowItems.map((cell, colIdx) => {
                const idx = startIdx + colIdx
                if (cell.kind === 'entry') {
                  const entry = cell.item
                  return (
                    <EntryCard
                      key={entry.id}
                      item={entry}
                      selected={selectedIds.has(entry.id)}
                      thumbnailVersion={thumbnailVersion}
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
                        setDropIndicator(null)
                      }}
                      onDrop={(e) => commitDrop(e, entry.id)}
                      onSelect={(e) => onSelect(entry.id, e, idx)}
                      onDoubleClick={() => onDoubleClickEntry(entry)}
                      onContextMenu={(e) => onContextMenu(e, entry.id)}
                    />
                  )
                }
                const mediaItem = cell.item
                return (
                  <MediaCard
                    key={mediaItem.id}
                    item={mediaItem}
                    selected={selectedIds.has(mediaItem.id)}
                    thumbnailVersion={thumbnailVersion}
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
                      setDropIndicator(null)
                    }}
                    onDrop={(e) => commitDrop(e, mediaItem.id)}
                    onSelect={(e) => onSelect(mediaItem.id, e, idx)}
                    onDoubleClick={() => onDoubleClickMedia(mediaItem, media.findIndex((m) => m.id === mediaItem.id))}
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
