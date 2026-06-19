import { memo } from 'react'
import type { MediaItem } from '../../api/types'
import { api } from '../../api/client'

interface LightboxThumbnailStripProps {
  items: MediaItem[]
  resolvedIndex: number
  onSelectIndex: (index: number) => void
}

export const LightboxThumbnailStrip = memo(function LightboxThumbnailStrip({
  items,
  resolvedIndex,
  onSelectIndex,
}: LightboxThumbnailStripProps) {
  return (
    <div className="px-4 py-3 border-t border-white/10 overflow-x-auto">
      <div className="flex gap-2 justify-center min-w-min">
        {items.map((m, i) => (
          <button
            key={m.id}
            type="button"
            onClick={() => onSelectIndex(i)}
            className={`shrink-0 w-16 h-12 rounded overflow-hidden border-2 transition-colors ${
              i === resolvedIndex ? 'border-[var(--color-accent)]' : 'border-transparent opacity-60 hover:opacity-100'
            }`}
          >
            <img
              src={api.mediaThumbUrl(m.path, m.media_type)}
              alt=""
              draggable={false}
              onDragStart={(e) => e.preventDefault()}
              className="w-full h-full object-cover"
            />
          </button>
        ))}
      </div>
    </div>
  )
})
