import { useCallback, useEffect, useRef } from 'react'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { measureMpvBounds, mpvAttach, mpvDetach, mpvSetBounds } from '../../lib/mpvPlayer'

const ATTACH_RETRY_DELAYS_MS = [0, 80, 160, 320, 640, 960]
const MAX_ATTACH_ATTEMPTS = ATTACH_RETRY_DELAYS_MS.length

interface MpvVideoSurfaceProps {
  filePath: string
  active: boolean
  className?: string
  layoutRevision?: number
  onReady?: () => void
  onError?: (message: string) => void
  onRetry?: (attempt: number, maxAttempts: number) => void
}

export function MpvVideoSurface({
  filePath,
  active,
  className,
  layoutRevision = 0,
  onReady,
  onError,
  onRetry,
}: MpvVideoSurfaceProps) {
  const surfaceRef = useRef<HTMLDivElement | null>(null)
  const attachedRef = useRef(false)
  const attachingRef = useRef(false)
  const onReadyRef = useRef(onReady)
  const onErrorRef = useRef(onError)
  const onRetryRef = useRef(onRetry)
  const syncFrameRef = useRef<number | null>(null)

  useEffect(() => {
    onReadyRef.current = onReady
    onErrorRef.current = onError
    onRetryRef.current = onRetry
  }, [onError, onReady, onRetry])

  const syncBounds = useCallback(async () => {
    const element = surfaceRef.current
    if (!element || !attachedRef.current) return
    const bounds = await measureMpvBounds(element)
    await mpvSetBounds(bounds)
  }, [])

  const scheduleSyncBounds = useCallback(() => {
    if (syncFrameRef.current !== null) return
    syncFrameRef.current = window.requestAnimationFrame(() => {
      syncFrameRef.current = null
      void syncBounds().catch(() => {})
    })
  }, [syncBounds])

  const scheduleSyncBoundsRef = useRef(scheduleSyncBounds)
  scheduleSyncBoundsRef.current = scheduleSyncBounds

  useEffect(() => {
    if (!active || !filePath) {
      attachedRef.current = false
      attachingRef.current = false
      void mpvDetach().catch(() => {})
      return
    }

    let cancelled = false

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, ms)
      })

    const attach = async () => {
      if (attachingRef.current) return
      attachingRef.current = true
      let lastError = 'mpv attach failed'

      try {
        await mpvDetach().catch(() => {})
        if (cancelled) return
        await sleep(60)

        for (let attempt = 0; attempt < MAX_ATTACH_ATTEMPTS; attempt += 1) {
          if (cancelled) return
          if (attempt > 0) {
            onRetryRef.current?.(attempt + 1, MAX_ATTACH_ATTEMPTS)
            await sleep(ATTACH_RETRY_DELAYS_MS[attempt])
            if (cancelled) return
            await mpvDetach().catch(() => {})
            await sleep(40)
          }

          try {
            await new Promise<void>((resolve) => {
              requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
            })
            if (cancelled) return

            const element = surfaceRef.current
            if (!element) {
              lastError = 'mpv surface element missing'
              continue
            }

            const bounds = await measureMpvBounds(element, attempt === 0 ? 3000 : 5000)
            await mpvAttach(filePath, bounds)
            if (cancelled) {
              await mpvDetach().catch(() => {})
              return
            }
            attachedRef.current = true
            onReadyRef.current?.()
            scheduleSyncBoundsRef.current()
            return
          } catch (error) {
            lastError = String(error)
            attachedRef.current = false
          }
        }

        onErrorRef.current?.(lastError)
      } finally {
        attachingRef.current = false
      }
    }

    void attach()

    return () => {
      cancelled = true
      attachedRef.current = false
      attachingRef.current = false
      void mpvDetach().catch(() => {})
    }
  }, [active, filePath])

  useEffect(() => {
    if (!active || !attachedRef.current) return
    scheduleSyncBounds()
  }, [active, layoutRevision, scheduleSyncBounds])

  useEffect(() => {
    if (!active) return

    const element = surfaceRef.current
    if (!element) return

    const resizeObserver = new ResizeObserver(() => {
      scheduleSyncBounds()
    })
    resizeObserver.observe(element)

    let unlistenMove: (() => void) | null = null
    let unlistenResize: (() => void) | null = null

    void getCurrentWindow().onMoved(() => {
      scheduleSyncBounds()
    }).then((dispose) => {
      unlistenMove = dispose
    })

    void getCurrentWindow().onResized(() => {
      scheduleSyncBounds()
    }).then((dispose) => {
      unlistenResize = dispose
    })

    return () => {
      resizeObserver.disconnect()
      unlistenMove?.()
      unlistenResize?.()
      if (syncFrameRef.current !== null) {
        window.cancelAnimationFrame(syncFrameRef.current)
        syncFrameRef.current = null
      }
    }
  }, [active, scheduleSyncBounds])

  return (
    <div
      ref={surfaceRef}
      className={className ?? 'h-full w-full max-h-full max-w-full rounded-[var(--radius-md)] bg-black shadow-2xl'}
      aria-label="原生影片播放器"
    />
  )
}
