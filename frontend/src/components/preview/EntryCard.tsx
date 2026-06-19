import type { EntryItem } from '../../api/types'
import { api } from '../../api/client'
import { cn } from '../../lib/utils'
import { useState } from 'react'
import { GripVertical, Film, ImageIcon } from 'lucide-react'

interface EntryCardProps {
  item: EntryItem
  selected: boolean
  thumbnailVersion?: number
  sortable?: boolean
  dragging?: boolean
  dropPosition?: 'before' | 'after' | null
  onSelect: (e: React.MouseEvent) => void
  onSelectToggle?: (e: React.MouseEvent) => void
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
  onSelectToggle,
  onDoubleClick,
  onContextMenu,
  onDragStart,
  onDragOverItem,
  onDragLeave,
  onDrop,
}: EntryCardProps) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null)
  const thumbnailSrc = api.entryThumbUrl(item.path, thumbnailVersion)
  const loaded = loadedSrc === thumbnailSrc

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
      onClick={onSelect}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      className={cn(
        'card-hover relative flex flex-col rounded-[var(--radius-md)] border bg-[var(--color-panel)] cursor-pointer outline-none focus:outline-none focus-visible:outline-none',
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
      <div className="relative aspect-[12/8.5] bg-[var(--color-panel-2)] m-2 mb-0 rounded-[var(--radius-sm)] overflow-hidden">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onSelectToggle?.(e)
          }}
          className={cn(
            'absolute left-2 top-2 z-10 w-6 h-6 rounded-full border flex items-center justify-center text-xs transition-colors outline-none focus:outline-none focus-visible:outline-none',
            selected
              ? 'bg-[var(--color-accent)] border-[var(--color-accent)] text-white'
              : 'bg-white/85 border-white/80 text-[var(--color-text-muted)] hover:text-[var(--color-accent)]',
          )}
          title="選取此資料夾"
        >
          {selected ? '✓' : ''}
        </button>
        {!loaded && <div className="absolute inset-0 skeleton" />}
        <img
          src={thumbnailSrc}
          alt={item.subfolder_name}
          draggable={false}
          onDragStart={(e) => e.preventDefault()}
          className={cn('w-full h-full object-contain', loaded ? 'opacity-100' : 'opacity-0')}
          loading="lazy"
          onLoad={() => setLoadedSrc(thumbnailSrc)}
          onError={() => setLoadedSrc(thumbnailSrc)}
        />
        {item.preview_type && (
          <span className="absolute bottom-1.5 right-1.5 p-1 rounded bg-black/50 text-white">
            {item.preview_type === 'video' ? <Film className="w-3 h-3" /> : <ImageIcon className="w-3 h-3" />}
          </span>
        )}
      </div>
      <div className="p-3 pt-2 flex flex-col gap-1 min-h-[72px]">
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
