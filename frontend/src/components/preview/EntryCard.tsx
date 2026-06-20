import type { EntryItem } from '../../api/types'
import { cn } from '../../lib/utils'
import { useRef, useState } from 'react'
import { GripVertical } from 'lucide-react'
import { EntryFanPreview } from './EntryFanPreview'

interface EntryCardProps {
  item: EntryItem
  selected: boolean
  thumbnailVersion?: number
  sortable?: boolean
  dragging?: boolean
  dropPosition?: 'before' | 'after' | null
  onSelect: (e: React.MouseEvent) => void
  onDoubleClick: () => void
  onContextMenu: (e: React.MouseEvent) => void
  onDragStart?: (e: React.DragEvent<HTMLElement>) => void
  onDragOverItem?: (e: React.DragEvent<HTMLDivElement>) => void
  onDragLeave?: () => void
  onDrop?: (e: React.DragEvent<HTMLDivElement>) => void
}

export function EntryCard({
  item,
  selected,
  thumbnailVersion = 0,
  sortable,
  dragging,
  dropPosition,
  onSelect,
  onDoubleClick,
  onContextMenu,
  onDragStart,
  onDragOverItem,
  onDragLeave,
  onDrop,
}: EntryCardProps) {
  const [hovered, setHovered] = useState(false)
  const clickTimerRef = useRef<number | null>(null)
  const fanSamples = item.preview_samples ?? []
  const hasFan = fanSamples.length >= 2

  const startInternalDrag = (e: React.DragEvent<HTMLElement>) => {
    if (!sortable) {
      e.preventDefault()
      return
    }
    e.stopPropagation()
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('application/x-people-folder-manager-item', item.id)
    onDragStart?.(e)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onDragOver={(e) => {
        if (!sortable) return
        e.preventDefault()
        onDragOverItem?.(e)
      }}
      onDragLeave={() => onDragLeave?.()}
      onDrop={(e) => {
        e.preventDefault()
        onDrop?.(e)
      }}
      onClick={(e) => {
        if (clickTimerRef.current !== null) {
          window.clearTimeout(clickTimerRef.current)
        }
        clickTimerRef.current = window.setTimeout(() => {
          clickTimerRef.current = null
          onSelect(e)
        }, 220)
      }}
      onDoubleClick={() => {
        if (clickTimerRef.current !== null) {
          window.clearTimeout(clickTimerRef.current)
          clickTimerRef.current = null
        }
        onDoubleClick()
      }}
      onContextMenu={onContextMenu}
      className={cn(
        'card-hover relative flex flex-col rounded-[var(--radius-md)] border bg-[var(--color-panel)] cursor-pointer outline-none focus:outline-none focus-visible:outline-none',
        hasFan && 'overflow-visible',
        hasFan && hovered && 'z-20',
        dragging && 'z-30 scale-[1.015] opacity-60 shadow-[var(--shadow-md)]',
        selected
          ? 'border-[var(--color-accent)] shadow-[0_0_0_2px_var(--color-accent-soft)]'
          : 'border-[var(--color-border)]',
      )}
    >
      {dropPosition && (
        <div
          className={cn(
            'absolute top-2 bottom-2 z-20 w-1.5 rounded-full bg-[var(--color-accent)] shadow-[0_0_0_3px_var(--color-accent-soft)]',
            dropPosition === 'before' ? '-left-2.5' : '-right-2.5',
          )}
        />
      )}
      <div
        className={cn(
          'relative aspect-[12/8.5] m-2 mb-0 rounded-[var(--radius-sm)]',
          hasFan ? 'overflow-visible' : 'overflow-hidden bg-[var(--color-panel-2)]',
          hasFan && hovered && 'z-20',
        )}
      >
        {hasFan && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-[var(--radius-sm)] bg-[var(--color-panel-2)]"
          />
        )}
        <EntryFanPreview
          samples={fanSamples}
          folderPath={item.path}
          previewType={item.preview_type}
          thumbnailVersion={thumbnailVersion}
          alt={item.subfolder_name}
          expanded={hovered}
        />
      </div>
      <div className="relative z-0 p-3 pt-2 flex flex-col gap-1 min-h-[72px] bg-[var(--color-panel)] rounded-b-[var(--radius-md)]">
        <p className="text-sm font-semibold truncate" title={item.subfolder_name}>
          {item.subfolder_name}
        </p>
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-[var(--color-text-muted)]">媒體數量：{item.media_count}</p>
          <span
            draggable={Boolean(sortable)}
            onDragStart={startInternalDrag}
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-xs text-[var(--color-accent)] cursor-grab active:cursor-grabbing"
          >
            <GripVertical className="w-3.5 h-3.5" />
            拖動排序
          </span>
        </div>
      </div>
    </div>
  )
}
