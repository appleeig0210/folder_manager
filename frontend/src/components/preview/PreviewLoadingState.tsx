import { useEffect, useState } from 'react'

interface PreviewLoadingStateProps {
  /** 固定文字，右側會附加跳動的 .... */
  label?: string
  /** fetch = 等待後端回應；render = 大量 card 正在掛載到畫面 */
  phase?: 'fetch' | 'render'
}

const PHASE_LABEL: Record<NonNullable<PreviewLoadingStateProps['phase']>, string> = {
  fetch: '讀取預覽',
  render: '整理畫面',
}

// 階段式填充：等待 API 時緩動逼近 60%（封頂，避免假裝快完成），
// 進入渲染階段跳到 92%，完成瞬間元件卸載後由 grid 取代。
const FETCH_CAP = 0.6
const RENDER_TARGET = 0.92

export function PreviewLoadingState({ label, phase = 'fetch' }: PreviewLoadingStateProps) {
  const statusLabel = label ?? PHASE_LABEL[phase]
  const [progress, setProgress] = useState(0.08)

  useEffect(() => {
    if (phase === 'render') {
      setProgress((current) => Math.max(current, RENDER_TARGET))
      return
    }
    setProgress((current) => Math.min(current, FETCH_CAP))
    const id = window.setInterval(() => {
      setProgress((current) => (current >= FETCH_CAP ? current : current + (FETCH_CAP - current) * 0.12))
    }, 180)
    return () => window.clearInterval(id)
  }, [phase])

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-5 px-6 py-12">
      <div
        className="flex items-end gap-0.5 text-sm text-[var(--color-text-muted)]"
        role="status"
        aria-live="polite"
        aria-label={`${statusLabel}…`}
      >
        <span>{statusLabel}</span>
        <span className="loading-dots mb-px" aria-hidden="true">
          <span>.</span>
          <span>.</span>
          <span>.</span>
          <span>.</span>
        </span>
      </div>
      <div className="w-full max-w-sm h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
        <div
          className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-300 ease-out"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>
    </div>
  )
}
