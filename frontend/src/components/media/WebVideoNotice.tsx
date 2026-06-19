import { Monitor } from 'lucide-react'
import { getRecommendedDevCommand, WEB_LIMITATIONS } from '../../lib/platform'

export function WebVideoNotice() {
  return (
    <div className="mx-auto mb-2 flex max-w-4xl items-start gap-2 rounded-[var(--radius-md)] border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
      <Monitor className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p>
        瀏覽器模式僅支援 HTTP 影片串流，精細拖動與 mpv 內嵌請改用桌面版{' '}
        <code className="rounded bg-black/20 px-1 font-mono">{getRecommendedDevCommand()}</code>
        。{WEB_LIMITATIONS.videoPipeline === 'http-only' ? '（無 asset / mpv）' : ''}
      </p>
    </div>
  )
}
