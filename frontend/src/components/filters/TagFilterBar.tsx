import type { FilterState } from '../../api/types'
import { cn } from '../../lib/utils'

interface TagFilterBarProps {
  allTags: string[]
  filter: FilterState
  expanded: boolean
  onToggleExpand: () => void
  onToggleTag: (tag: string) => void
}

export function TagFilterBar({ allTags, filter, expanded, onToggleExpand, onToggleTag }: TagFilterBarProps) {
  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-panel)] px-4 py-2">
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-xs font-semibold text-[var(--color-text)]">標籤篩選（勾選即套用 OR）</span>
        <button
          type="button"
          onClick={onToggleExpand}
          className="text-xs text-[var(--color-accent)] hover:underline"
        >
          {expanded ? '收合標籤' : '展開標籤'}
        </button>
      </div>
      {expanded && (
        <div className="flex flex-wrap gap-2 max-h-24 overflow-y-auto">
          {allTags.length === 0 && (
            <span className="text-xs text-[var(--color-text-muted)]">尚無標籤</span>
          )}
          {allTags.map((tag) => {
            const active = filter.selected_tags.includes(tag)
            return (
              <button
                key={tag}
                type="button"
                onClick={() => onToggleTag(tag)}
                className={cn(
                  'px-3 py-1 rounded-[var(--radius-pill)] text-xs font-medium transition-colors border',
                  active
                    ? 'bg-[var(--color-accent)] text-white border-[var(--color-accent)]'
                    : 'bg-[var(--color-panel-2)] text-[var(--color-text-muted)] border-[var(--color-border)] hover:border-[var(--color-accent)]',
                )}
              >
                {tag}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
