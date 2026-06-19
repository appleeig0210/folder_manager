import { memo, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import {
  readRangeSeconds,
  shouldHandleScrubInput,
  syncScrubRangeVisual,
  coarseScrubProgress,
  fineScrubProgress,
} from './videoScrub'

export const FINE_SEEK_WINDOW_SECONDS = 4
export const FINE_SEEK_STEP_SECONDS = 1 / 60
export const FINE_SEEK_NUDGE_SECONDS = 0.02

function formatTimestamp(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00.00'
  const minutes = Math.floor(seconds / 60)
  const wholeSeconds = Math.floor(seconds % 60)
  const centiseconds = Math.floor((seconds % 1) * 100)
  return `${minutes}:${wholeSeconds.toString().padStart(2, '0')}.${centiseconds.toString().padStart(2, '0')}`
}

function formatTimestampFine(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00.000'
  const minutes = Math.floor(seconds / 60)
  const wholeSeconds = Math.floor(seconds % 60)
  const millis = Math.floor((seconds % 1) * 1000)
  return `${minutes}:${wholeSeconds.toString().padStart(2, '0')}.${millis.toString().padStart(3, '0')}`
}

export interface VideoTimelineControlsProps {
  displayedTime: number
  videoDuration: number
  coarseSeekValue: number
  coarseSeekProgress: number
  fineSeekStart: number
  fineSeekEnd: number
  fineSeekValue: number
  fineSeekProgress: number
  onStartCoarseScrub: () => void
  onPreviewCoarseSeek: (seconds: number) => void
  onStartFineScrub: () => void
  onPreviewFineSeek: (seconds: number) => void
  onScrubPointerActivate: (input: HTMLInputElement) => void
  onEndScrubFromInput: (event: { currentTarget: HTMLInputElement; pointerId?: number }) => void
  isScrubPointerActive: () => boolean
  onScrubPointerMove: (
    event: ReactPointerEvent<HTMLInputElement>,
    preview: (seconds: number, input: HTMLInputElement) => void,
  ) => void
  onSeekVideoTo: (seconds: number) => void
  readVideoTime: () => number
}

export const VideoTimelineControls = memo(function VideoTimelineControls({
  displayedTime,
  videoDuration,
  coarseSeekValue,
  coarseSeekProgress,
  fineSeekStart,
  fineSeekEnd,
  fineSeekValue,
  fineSeekProgress,
  onStartCoarseScrub,
  onPreviewCoarseSeek,
  onStartFineScrub,
  onPreviewFineSeek,
  onScrubPointerActivate,
  onEndScrubFromInput,
  isScrubPointerActive,
  onScrubPointerMove,
  onSeekVideoTo,
  readVideoTime,
}: VideoTimelineControlsProps) {
  return (
    <div className="px-6 pb-2 text-white">
      <div className="mx-auto flex max-w-4xl flex-col gap-2 rounded-[var(--radius-md)] border border-white/10 bg-white/5 px-4 py-2">
        <div className="flex items-center justify-between gap-3 text-xs text-white/65">
          <span>目前 {formatTimestampFine(displayedTime)}</span>
          <span>{videoDuration > 0 ? `總長 ${formatTimestamp(videoDuration)}` : '讀取時間中…'}</span>
        </div>
        {videoDuration > 0 && (
          <div className="flex items-center gap-3">
            <span className="w-[7.5rem] shrink-0 text-[11px] leading-snug text-white/45">
              全片時間軸
            </span>
            <div className="video-scrub-range-wrap min-w-0 flex-1">
              <div className="video-scrub-range-track" aria-hidden>
                <div
                  className="video-scrub-range-fill video-scrub-range-fill--coarse"
                  style={{ width: `${coarseSeekProgress}%` }}
                />
              </div>
              <div
                className="video-scrub-range-thumb"
                style={{ '--scrub-progress': coarseSeekProgress / 100 } as CSSProperties}
                aria-hidden
              />
              <input
                type="range"
                min={0}
                max={videoDuration}
                step="any"
                value={coarseSeekValue}
                onPointerDown={(event) => {
                  event.currentTarget.setPointerCapture(event.pointerId)
                  onScrubPointerActivate(event.currentTarget)
                  onStartCoarseScrub()
                }}
                onPointerMove={(event) => onScrubPointerMove(event, onPreviewCoarseSeek)}
                onPointerUp={onEndScrubFromInput}
                onPointerCancel={onEndScrubFromInput}
                onMouseUp={onEndScrubFromInput}
                onLostPointerCapture={onEndScrubFromInput}
                onInput={(event) => {
                  if (!shouldHandleScrubInput(isScrubPointerActive())) return
                  const seconds = readRangeSeconds(event)
                  syncScrubRangeVisual(event.currentTarget, coarseScrubProgress(seconds, videoDuration))
                  onPreviewCoarseSeek(seconds)
                }}
                className="video-scrub-range w-full"
                aria-label="全片時間軸"
              />
            </div>
          </div>
        )}
        <div className="flex items-center gap-3">
          <span className="w-[7.5rem] shrink-0 text-[11px] leading-snug text-white/45">
            精細微調
          </span>
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <button
              type="button"
              onClick={() => onSeekVideoTo(readVideoTime() - 1)}
              className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
            >
              -1s
            </button>
            <button
              type="button"
              onClick={() => onSeekVideoTo(readVideoTime() - FINE_SEEK_NUDGE_SECONDS)}
              className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
            >
              -0.02s
            </button>
            <button
              type="button"
              onClick={() => onSeekVideoTo(readVideoTime() - FINE_SEEK_STEP_SECONDS)}
              className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
              title="倒退 1 影格（約 1/60 秒）"
            >
              -1f
            </button>
            <div className="video-scrub-range-wrap video-scrub-range-wrap--fine min-w-0 flex-1">
              <div className="video-scrub-range-track" aria-hidden>
                <div
                  className="video-scrub-range-fill video-scrub-range-fill--fine"
                  style={{ width: `${fineSeekProgress}%` }}
                />
              </div>
              <div
                className="video-scrub-range-thumb"
                style={{ '--scrub-progress': fineSeekProgress / 100 } as CSSProperties}
                aria-hidden
              />
              <input
                type="range"
                min={fineSeekStart}
                max={fineSeekEnd}
                step="any"
                value={fineSeekValue}
                onPointerDown={(event) => {
                  event.currentTarget.setPointerCapture(event.pointerId)
                  onScrubPointerActivate(event.currentTarget)
                  onStartFineScrub()
                }}
                onPointerMove={(event) => onScrubPointerMove(event, onPreviewFineSeek)}
                onPointerUp={onEndScrubFromInput}
                onPointerCancel={onEndScrubFromInput}
                onMouseUp={onEndScrubFromInput}
                onLostPointerCapture={onEndScrubFromInput}
                onInput={(event) => {
                  if (!shouldHandleScrubInput(isScrubPointerActive())) return
                  const seconds = readRangeSeconds(event)
                  syncScrubRangeVisual(event.currentTarget, fineScrubProgress(seconds, fineSeekStart, fineSeekEnd))
                  onPreviewFineSeek(seconds)
                }}
                className="video-scrub-range video-scrub-range--fine w-full"
                aria-label="精細調整影片時間"
              />
            </div>
            <button
              type="button"
              onClick={() => onSeekVideoTo(readVideoTime() + FINE_SEEK_STEP_SECONDS)}
              className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
              title="前進 1 影格（約 1/60 秒）"
            >
              +1f
            </button>
            <button
              type="button"
              onClick={() => onSeekVideoTo(readVideoTime() + FINE_SEEK_NUDGE_SECONDS)}
              className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
            >
              +0.02s
            </button>
            <button
              type="button"
              onClick={() => onSeekVideoTo(readVideoTime() + 1)}
              className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
            >
              +1s
            </button>
          </div>
        </div>
      </div>
    </div>
  )
})
