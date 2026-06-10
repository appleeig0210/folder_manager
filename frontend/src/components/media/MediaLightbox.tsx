import { AnimatePresence, motion } from 'framer-motion'
import { ChevronLeft, ChevronRight, ExternalLink, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { MediaItem } from '../../api/types'
import { api } from '../../api/client'
import { Button } from '../ui/Button'

interface MediaLightboxProps {
  items: MediaItem[]
  initialIndex: number
  onClose: () => void
}

export function MediaLightbox({ items, initialIndex, onClose }: MediaLightboxProps) {
  const [index, setIndex] = useState(initialIndex)
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const item = items[index]

  const prev = useCallback(() => {
    if (items.length <= 1) return
    setLoaded(false)
    setLoadError(false)
    setIndex((i) => (i - 1 + items.length) % items.length)
  }, [items.length])

  const next = useCallback(() => {
    if (items.length <= 1) return
    setLoaded(false)
    setLoadError(false)
    setIndex((i) => (i + 1) % items.length)
  }, [items.length])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
      if (e.key === 'Enter') item && api.openPath(item.path)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, prev, next, item])

  if (!item) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex flex-col bg-black/92"
      >
        <div className="flex items-center justify-between px-4 py-3 text-white">
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate">{item.name}</p>
            <p className="text-xs text-white/60">
              {index + 1} / {items.length} · {item.media_type === 'video' ? '影片' : '圖片'}
              {item.duration_label ? ` · ${item.duration_label}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              className="text-white hover:bg-white/10"
              onClick={() => api.openPath(item.path)}
            >
              <ExternalLink className="w-4 h-4" /> 以程式開啟
            </Button>
            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-[var(--radius-sm)] hover:bg-white/10 text-white"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="relative flex-1 flex items-center justify-center min-h-0 px-24 py-4">
          <button
            type="button"
            onClick={prev}
            className="absolute left-0 top-0 bottom-0 w-24 flex items-center justify-center text-white/80 hover:text-white hover:bg-white/5 transition-colors z-10"
            aria-label="上一張"
          >
            <ChevronLeft className="w-10 h-10" />
          </button>

          <div className="relative w-full h-full flex items-center justify-center">
            {!loaded && (
              <div className="absolute inset-0 flex items-center justify-center text-white/50">載入中…</div>
            )}
            {loadError ? (
              <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-white/70">
                <img
                  src={api.mediaThumbUrl(item.path, item.media_type)}
                  alt={item.name}
                  draggable={false}
                  onDragStart={(e) => e.preventDefault()}
                  className="max-h-[72vh] max-w-full rounded-[var(--radius-md)] object-contain shadow-2xl"
                  onLoad={() => setLoaded(true)}
                />
                <div className="text-center text-sm">
                  <p>無法直接載入原始檔，已改顯示預覽圖。</p>
                  <p className="mt-1 text-white/45">可按「以程式開啟」使用系統播放器或看圖工具。</p>
                </div>
              </div>
            ) : item.media_type === 'video' ? (
              <motion.video
                key={item.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: loaded ? 1 : 0 }}
                transition={{ duration: 0.2 }}
                src={api.mediaFileUrl(item.path)}
                className="max-w-full max-h-full rounded-[var(--radius-md)] bg-black shadow-2xl"
                controls
                autoPlay
                onLoadedData={() => setLoaded(true)}
                onError={() => {
                  setLoadError(true)
                  setLoaded(true)
                }}
              />
            ) : (
              <motion.img
                key={item.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: loaded ? 1 : 0 }}
                transition={{ duration: 0.2 }}
                src={api.mediaFileUrl(item.path)}
                alt={item.name}
                draggable={false}
                onDragStart={(e) => e.preventDefault()}
                className="max-w-full max-h-full object-contain rounded-[var(--radius-md)] shadow-2xl"
                onLoad={() => setLoaded(true)}
                onError={() => {
                  setLoadError(true)
                  setLoaded(true)
                }}
              />
            )}
          </div>

          <button
            type="button"
            onClick={next}
            className="absolute right-0 top-0 bottom-0 w-24 flex items-center justify-center text-white/80 hover:text-white hover:bg-white/5 transition-colors z-10"
            aria-label="下一張"
          >
            <ChevronRight className="w-10 h-10" />
          </button>
        </div>

        <div className="px-4 py-3 border-t border-white/10 overflow-x-auto">
          <div className="flex gap-2 justify-center min-w-min">
            {items.map((m, i) => (
              <button
                key={m.id}
                type="button"
                onClick={() => {
                  setLoaded(false)
                  setLoadError(false)
                  setIndex(i)
                }}
                className={`shrink-0 w-16 h-12 rounded overflow-hidden border-2 transition-colors ${
                  i === index ? 'border-[var(--color-accent)]' : 'border-transparent opacity-60 hover:opacity-100'
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

        <p className="text-center text-xs text-white/40 pb-3">
          ← → 切換 · Enter 以外部程式開啟 · Esc 關閉
        </p>
      </motion.div>
    </AnimatePresence>
  )
}
