import { ChevronRight } from 'lucide-react'
import type { BreadcrumbItem } from '../../api/types'
import { cn } from '../../lib/utils'

interface BreadcrumbProps {
  items: BreadcrumbItem[]
  onNavigate: (path: string) => void
  className?: string
}

export function Breadcrumb({ items, onNavigate, className }: BreadcrumbProps) {
  if (!items.length) return null
  return (
    <nav className={cn('flex items-center gap-1 min-w-0 text-sm', className)} aria-label="路徑導覽">
      {items.map((item, i) => (
        <span key={item.path} className="flex items-center gap-1 min-w-0">
          {i > 0 && <ChevronRight className="w-3.5 h-3.5 text-[var(--color-text-muted)] shrink-0" />}
          <button
            type="button"
            onClick={() => onNavigate(item.path)}
            className={cn(
              'truncate max-w-[180px] px-1.5 py-0.5 rounded-md transition-colors',
              i === items.length - 1
                ? 'text-[var(--color-text)] font-semibold'
                : 'text-[var(--color-text-muted)] hover:text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)]',
            )}
            title={item.name}
          >
            {item.name}
          </button>
        </span>
      ))}
    </nav>
  )
}
