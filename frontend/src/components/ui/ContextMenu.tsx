import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { cn } from '../../lib/utils'

export interface ContextMenuItem {
  label: string
  onClick: () => void
  danger?: boolean
  separator?: boolean
}

interface ContextMenuProps {
  x: number
  y: number
  items: ContextMenuItem[]
  onClose: () => void
}

const VIEWPORT_MARGIN = 8

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: x, top: y })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const maxLeft = window.innerWidth - width - VIEWPORT_MARGIN
    const maxTop = window.innerHeight - height - VIEWPORT_MARGIN
    // 靠右邊緣時往左展開（以游標為右緣），仍超出則夾在可視範圍內
    const left = Math.max(VIEWPORT_MARGIN, Math.min(x, maxLeft))
    const top = Math.max(VIEWPORT_MARGIN, Math.min(y, maxTop))
    setPosition({ left, top })
  }, [x, y, items])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('mousedown', handler)
    window.addEventListener('keydown', esc)
    return () => {
      window.removeEventListener('mousedown', handler)
      window.removeEventListener('keydown', esc)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      className="fixed z-[60] w-max min-w-[140px] max-w-[min(90vw,320px)] py-1 rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel)] shadow-[var(--shadow-md)]"
      style={{ left: position.left, top: position.top }}
    >
      {items.map((item, i) =>
        item.separator ? (
          <div key={i} className="my-1 border-t border-[var(--color-border)]" />
        ) : (
          <button
            key={i}
            type="button"
            onClick={() => {
              onClose()
              window.setTimeout(item.onClick, 0)
            }}
            className={cn(
              'block w-full whitespace-nowrap text-left px-3 py-2 text-sm hover:bg-[var(--color-panel-2)] transition-colors',
              item.danger ? 'text-[var(--color-danger)]' : 'text-[var(--color-text)]',
            )}
          >
            {item.label}
          </button>
        ),
      )}
    </div>
  )
}
