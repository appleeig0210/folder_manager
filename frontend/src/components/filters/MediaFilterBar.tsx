import type { FilterState, SortMode } from '../../api/types'
import { Button } from '../ui/Button'

interface MediaFilterBarProps {
  filter: FilterState
  viewMode: 'folder' | 'entries' | 'media'
  onChange: (patch: Partial<FilterState>) => void
  onApplyDuration: () => void
}

const SORT_OPTIONS: { value: SortMode; label: string }[] = [
  { value: 'name', label: '名稱' },
  { value: 'time', label: '時間' },
  { value: 'type', label: '類型' },
  { value: 'manual', label: '手動' },
]

export function MediaFilterBar({ filter, viewMode, onChange, onApplyDuration }: MediaFilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-panel)] text-sm">
      <label className="flex items-center gap-1.5 cursor-pointer">
        <input
          type="checkbox"
          checked={filter.media_video}
          onChange={(e) => onChange({ media_video: e.target.checked })}
          className="accent-[var(--color-accent)]"
        />
        <span>影片</span>
      </label>
      <label className="flex items-center gap-1.5 cursor-pointer">
        <input
          type="checkbox"
          checked={filter.media_image}
          onChange={(e) => onChange({ media_image: e.target.checked })}
          className="accent-[var(--color-accent)]"
        />
        <span>圖片</span>
      </label>
      {(viewMode === 'media' || viewMode === 'folder') && (
        <>
          <span className="text-[var(--color-text-muted)]">影片長度（分）</span>
          <input
            type="number"
            min={0}
            placeholder="最小"
            value={filter.duration_min ?? ''}
            onChange={(e) =>
              onChange({ duration_min: e.target.value === '' ? null : Number(e.target.value) })
            }
            className="w-20 h-8 px-2 rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel)] text-sm"
          />
          <span className="text-[var(--color-text-muted)]">～</span>
          <input
            type="number"
            min={0}
            placeholder="最大"
            value={filter.duration_max ?? ''}
            onChange={(e) =>
              onChange({ duration_max: e.target.value === '' ? null : Number(e.target.value) })
            }
            className="w-20 h-8 px-2 rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel)] text-sm"
          />
          <Button size="sm" onClick={onApplyDuration}>
            套用
          </Button>
        </>
      )}
      <div className="ml-auto flex items-center gap-2">
        <span className="text-[var(--color-text-muted)] text-xs">排序</span>
        <select
          value={filter.sort_mode}
          onChange={(e) => onChange({ sort_mode: e.target.value as SortMode })}
          className="h-8 px-2 rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel)] text-sm"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
