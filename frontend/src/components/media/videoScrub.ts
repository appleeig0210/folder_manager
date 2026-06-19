import type { PointerEvent as ReactPointerEvent } from 'react'

/** macOS WebKit 在 range 拖曳時常回報 buttons=0，需以 pointer 按下狀態判斷是否仍應更新。 */
export function shouldHandleScrubPointerMove(
  event: ReactPointerEvent<HTMLInputElement>,
  isPointerActive: boolean,
): boolean {
  if (isPointerActive) return true
  return event.buttons !== 0
}

/** 阻擋 macOS WebKit 在放開滑鼠後仍由原生 range 觸發的幽靈 input 事件。 */
export function shouldHandleScrubInput(isPointerActive: boolean): boolean {
  return isPointerActive
}

export function readRangeSeconds(event: { currentTarget: HTMLInputElement }): number {
  return Number(event.currentTarget.value)
}

export function syncScrubRangeVisual(input: HTMLInputElement, progressPercent: number): void {
  const wrap = input.closest('.video-scrub-range-wrap')
  if (!wrap) return
  const fill = wrap.querySelector('.video-scrub-range-fill') as HTMLElement | null
  const thumb = wrap.querySelector('.video-scrub-range-thumb') as HTMLElement | null
  const clamped = Math.min(100, Math.max(0, progressPercent))
  if (fill) fill.style.width = `${clamped}%`
  if (thumb) thumb.style.setProperty('--scrub-progress', String(clamped / 100))
}

export function coarseScrubProgress(seconds: number, duration: number): number {
  if (duration <= 0) return 0
  return (Math.min(Math.max(seconds, 0), duration) / duration) * 100
}

export function fineScrubProgress(
  seconds: number,
  start: number,
  end: number,
): number {
  if (end <= start) return 0
  const clamped = Math.min(Math.max(seconds, start), end)
  return ((clamped - start) / (end - start)) * 100
}
