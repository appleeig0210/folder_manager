import { Volume2, VolumeX } from 'lucide-react'
import { memo } from 'react'
import { cn } from '../../lib/utils'

export interface VideoVolumeControlProps {
  volume: number
  muted: boolean
  onVolumeChange: (volume: number) => void
  onToggleMute: () => void
  className?: string
  showPercent?: boolean
}

export const VideoVolumeControl = memo(function VideoVolumeControl({
  volume,
  muted,
  onVolumeChange,
  onToggleMute,
  className,
  showPercent = true,
}: VideoVolumeControlProps) {
  const percent = Math.round(volume * 100)
  const shownPercent = muted ? 0 : percent

  return (
    <div className={cn('flex min-w-0 items-center gap-2', className)}>
      <button
        type="button"
        onClick={onToggleMute}
        className="shrink-0 rounded bg-white/10 p-1.5 text-white/80 hover:bg-white/15 hover:text-white"
        aria-label={muted ? '取消靜音' : '靜音'}
        title={muted ? '取消靜音' : '靜音'}
      >
        {muted || volume === 0 ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
      </button>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={percent}
        onChange={(event) => onVolumeChange(Number(event.target.value) / 100)}
        className="video-volume-range min-w-0 flex-1"
        aria-label="影片音量"
      />
      {showPercent ? (
        <span className="w-9 shrink-0 text-right text-[11px] text-white/45">{shownPercent}%</span>
      ) : null}
    </div>
  )
})
