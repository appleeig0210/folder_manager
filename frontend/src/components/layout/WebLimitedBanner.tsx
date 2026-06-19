import { Monitor, X } from 'lucide-react'
import { getRecommendedDevCommand, WEB_LIMITATIONS } from '../../lib/platform'

const DISMISS_KEY = 'pfm-web-limited-banner-dismissed'

interface WebLimitedBannerProps {
  onDismiss?: () => void
}

export function WebLimitedBanner({ onDismiss }: WebLimitedBannerProps) {
  const dismiss = () => {
    window.localStorage.setItem(DISMISS_KEY, '1')
    onDismiss?.()
  }

  return (
    <div
      role="status"
      className="shrink-0 flex items-start gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-950 dark:text-amber-100"
    >
      <Monitor className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-300" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">目前為瀏覽器開發模式，功能受限</p>
        <p className="mt-0.5 text-xs opacity-90">
          {WEB_LIMITATIONS.note} 建議在專案根目錄執行{' '}
          <code className="rounded bg-black/10 px-1 py-0.5 font-mono text-[11px] dark:bg-white/10">
            {getRecommendedDevCommand()}
          </code>
        </p>
      </div>
      <button
        type="button"
        onClick={dismiss}
        className="shrink-0 rounded p-1 text-amber-700 hover:bg-amber-500/20 dark:text-amber-200"
        aria-label="關閉提示"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

export function isWebLimitedBannerDismissed(): boolean {
  return window.localStorage.getItem(DISMISS_KEY) === '1'
}
