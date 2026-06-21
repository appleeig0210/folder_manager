import { useEffect, useRef } from 'react'
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

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)

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
      className="fixed z-[60] min-w-[200px] py-1 rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel)] shadow-[var(--shadow-md)]"
      style={{ left: x, top: y }}
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
              'w-full text-left px-3 py-2 text-sm hover:bg-[var(--color-panel-2)] transition-colors',
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
