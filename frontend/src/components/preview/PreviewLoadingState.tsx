import { useEffect, useState } from 'react'

interface PreviewLoadingStateProps {
  /** 固定文字，右側會附加跳動的 .... */
  label?: string
}

export function PreviewLoadingState({ label = '載入中' }: PreviewLoadingStateProps) {
  const [progress, setProgress] = useState(0.06)

  useEffect(() => {
    setProgress(0.06)
    const id = window.setInterval(() => {
      setProgress((current) => (current >= 0.92 ? current : current + (0.92 - current) * 0.12))
    }, 180)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-5 px-6 py-12">
      <div
        className="flex items-end gap-0.5 text-sm text-[var(--color-text-muted)]"
        role="status"
        aria-live="polite"
        aria-label={`${label}…`}
      >
        <span>{label}</span>
        <span className="loading-dots mb-px" aria-hidden="true">
          <span>.</span>
          <span>.</span>
          <span>.</span>
          <span>.</span>
        </span>
      </div>
      <div className="w-full max-w-sm h-1.5 rounded-full bg-[var(--color-border)] overflow-hidden">
        <div
          className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-200 ease-out"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>
    </div>
  )
}
