import type { MediaItem } from '../../api/types'
import { api } from '../../api/client'
import { cn } from '../../lib/utils'
import { memo, useState } from 'react'
import { GripVertical, Film, ImageIcon, Upload } from 'lucide-react'

interface MediaCardProps {
  item: MediaItem
  selected: boolean
  thumbnailVersion?: number
  sortable?: boolean
  dragging?: boolean
  dropPosition?: 'before' | 'after' | null
  onSelect: (e: React.MouseEvent) => void
  onDoubleClick: () => void
  onContextMenu: (e: React.MouseEvent) => void
  nativeDragPaths?: string[]
  onNativeFileDragStart?: (e: React.DragEvent<HTMLElement>, paths: string[]) => void
  onDragStart?: (e: React.DragEvent<HTMLElement>) => void
  onDragOverItem?: (e: React.DragEvent<HTMLDivElement>) => void
  onDragLeave?: () => void
  onDrop?: (e: React.DragEvent<HTMLDivElement>) => void
}

export const MediaCard = memo(function MediaCard({
  item,
  selected,
  thumbnailVersion = 0,
  sortable,
  dragging,
  dropPosition,
  onSelect,
  onDoubleClick,
  onContextMenu,
  nativeDragPaths,
  onNativeFileDragStart,
  onDragStart,
  onDragOverItem,
  onDragLeave,
  onDrop,
}: MediaCardProps) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null)
  const canNativeDrag = Boolean(nativeDragPaths?.length)
  const tags = item.tags.length ? item.tags.join(', ') : '（尚未標籤）'
  const thumbnailSrc = api.mediaThumbUrl(item.path, item.media_type, thumbnailVersion)
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

  const startNativeDrag = (e: React.DragEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    if (nativeDragPaths?.length) {
      onNativeFileDragStart?.(e, nativeDragPaths)
    }
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
      <div
        draggable={canNativeDrag}
        onDragStart={startNativeDrag}
        className={cn(
          'relative aspect-[6/5] bg-[var(--color-panel-2)] m-2 mb-0 rounded-[var(--radius-sm)] overflow-hidden',
          canNativeDrag && 'cursor-grab active:cursor-grabbing',
        )}
        title={canNativeDrag ? '拖曳原始檔到外部應用' : undefined}
      >
        {!loaded && <div className="absolute inset-0 skeleton" />}
        <img
          src={thumbnailSrc}
          alt={item.name}
          draggable={false}
          onDragStart={(e) => e.preventDefault()}
          className={cn('w-full h-full object-contain', loaded ? 'opacity-100' : 'opacity-0')}
          loading="lazy"
          onLoad={() => setLoadedSrc(thumbnailSrc)}
          onError={() => setLoadedSrc(thumbnailSrc)}
        />
        <span className="absolute bottom-1.5 right-1.5 p-1 rounded bg-black/50 text-white">
          {item.media_type === 'video' ? <Film className="w-3 h-3" /> : <ImageIcon className="w-3 h-3" />}
        </span>
        {canNativeDrag && (
          <span className="absolute top-1.5 right-1.5 inline-flex items-center gap-1 rounded-full bg-black/55 px-2 py-1 text-[11px] font-medium text-white">
            <Upload className="w-3 h-3" />
            拖出
          </span>
        )}
      </div>
      <div className="p-3 pt-2 flex flex-col gap-1">
        <p className="text-sm font-semibold truncate" title={item.name}>
          {item.name}
        </p>
        <p className="text-xs text-[var(--color-text-muted)] truncate" title={tags}>
          標籤：{tags}
        </p>
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-[var(--color-text-muted)] truncate">
            類型：{item.media_type === 'video' ? '影片' : '圖片'}
            {item.duration_label ? ` · ${item.duration_label}` : ''}
          </p>
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
})
