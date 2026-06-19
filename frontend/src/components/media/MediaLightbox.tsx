import { AnimatePresence, motion } from 'framer-motion'
import { ChevronLeft, ChevronRight, ExternalLink, X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import type { MediaItem } from '../../api/types'
import { api } from '../../api/client'
import { prepareStreamableVideo, resolveMediaPlaybackSource, type MediaPlaybackSource } from '../../lib/mediaPlayback'
import { isNativeMpvAvailable, mpvDetach, mpvGetDuration, mpvGetTime, mpvSeek, mpvSetPaused } from '../../lib/mpvPlayer'
import { getMpvScrubProfile, getVideoScrubProfile, shouldUseServerFrameExtract, type VideoScrubProfile } from '../../lib/platform'
import { getVideoPlaybackModeInfo, playbackModeBadgeClass } from '../../lib/playbackDiagnostics'
import { MpvVideoSurface } from './MpvVideoSurface'
import { disposeVideoElement } from './videoUtils'
import { Button } from '../ui/Button'

const VIDEO_SEEK_STEP_SECONDS = 1 / 30
const VIDEO_HOLD_SEEK_STEP_SECONDS = 1 / 60
const VIDEO_HOLD_SEEK_INTERVAL_MS = 90
const VIDEO_SEEK_SETTLE_TIMEOUT_MS = 180
const FINE_SEEK_WINDOW_SECONDS = 4
const FINE_SEEK_STEP_SECONDS = 1 / 60
const FINE_SEEK_NUDGE_SECONDS = 0.02

interface MediaLightboxProps {
  items: MediaItem[]
  initialIndex: number
  onClose: () => void
  onStatus?: (message: string) => void
  onFrameSaved?: (message: string) => void | Promise<void>
}

export function MediaLightbox({ items, initialIndex, onClose, onStatus, onFrameSaved }: MediaLightboxProps) {
  const [index, setIndex] = useState(initialIndex)
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [videoTime, setVideoTime] = useState(0)
  const [videoDuration, setVideoDuration] = useState(0)
  const [fineSeekCenter, setFineSeekCenter] = useState(0)
  const [scrubbing, setScrubbing] = useState(false)
  const [scrubMode, setScrubMode] = useState<'coarse' | 'fine' | null>(null)
  const [scrubDraftTime, setScrubDraftTime] = useState<number | null>(null)
  const [videoPlayback, setVideoPlayback] = useState<MediaPlaybackSource | null>(null)
  const [mpvMode, setMpvMode] = useState(false)
  const [mpvReady, setMpvReady] = useState(false)
  const [mpvProbeDone, setMpvProbeDone] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const savingFrameRef = useRef(false)
  const holdSeekTimerRef = useRef<number | null>(null)
  const coarsePreviewTimerRef = useRef<number | null>(null)
  const pendingCoarseSeekRef = useRef<number | null>(null)
  const lastCoarsePreviewAtRef = useRef(0)
  const finePreviewTimerRef = useRef<number | null>(null)
  const pendingFineSeekRef = useRef<number | null>(null)
  const lastFinePreviewAtRef = useRef(0)
  const scrubbingRef = useRef(false)
  const scrubDraftRef = useRef<number | null>(null)
  const resumeAfterScrubRef = useRef(false)
  const seekingRef = useRef(false)
  const seekTokenRef = useRef(0)
  const scrubSeekingRef = useRef(false)
  const scrubModeRef = useRef<'coarse' | 'fine' | null>(null)
  const lastAppliedScrubSeekRef = useRef<number | null>(null)
  const scrubProfileRef = useRef<VideoScrubProfile>(getVideoScrubProfile(null))
  const mpvModeRef = useRef(false)
  const mpvReadyRef = useRef(false)
  const mpvPausedRef = useRef(false)
  const lastPolledMpvTimeRef = useRef(0)
  const [mpvLayoutRevision, setMpvLayoutRevision] = useState(0)
  const activeItemIdRef = useRef(items[initialIndex]?.id)
  const activeIndex = activeItemIdRef.current
    ? items.findIndex((candidate) => candidate.id === activeItemIdRef.current)
    : -1
  const resolvedIndex = activeIndex >= 0 ? activeIndex : Math.min(index, Math.max(0, items.length - 1))
  const item = items[resolvedIndex]
  const playbackProfile = mpvMode && mpvReady
    ? getMpvScrubProfile()
    : getVideoScrubProfile(videoPlayback)
  const displayedTime = scrubDraftTime ?? videoTime
  const fineSeekAnchor = scrubbing && scrubMode === 'coarse'
    ? displayedTime
    : fineSeekCenter
  const fineSeekStart = Math.max(0, fineSeekAnchor - FINE_SEEK_WINDOW_SECONDS / 2)
  const fineSeekEnd = videoDuration > 0
    ? Math.min(videoDuration, fineSeekAnchor + FINE_SEEK_WINDOW_SECONDS / 2)
    : fineSeekAnchor + FINE_SEEK_WINDOW_SECONDS / 2
  const fineSeekValue = Math.min(Math.max(displayedTime, fineSeekStart), fineSeekEnd)
  const coarseSeekValue = Math.min(Math.max(displayedTime, 0), videoDuration || 0)
  const coarseSeekProgress = videoDuration > 0 ? (coarseSeekValue / videoDuration) * 100 : 0
  const fineSeekProgress = fineSeekEnd > fineSeekStart
    ? ((fineSeekValue - fineSeekStart) / (fineSeekEnd - fineSeekStart)) * 100
    : 0
  const playbackModeInfo = useMemo(() => {
    if (item?.media_type !== 'video') return null
    return getVideoPlaybackModeInfo({ mpvProbeDone, mpvMode, mpvReady, videoPlayback })
  }, [item?.media_type, mpvProbeDone, mpvMode, mpvReady, videoPlayback])

  const selectIndex = useCallback((nextIndex: number) => {
    const nextItem = items[nextIndex]
    if (nextItem) activeItemIdRef.current = nextItem.id
    setLoaded(false)
    setLoadError(false)
    setIndex(nextIndex)
  }, [items])

  const prev = useCallback(() => {
    if (items.length <= 1) return
    selectIndex((resolvedIndex - 1 + items.length) % items.length)
  }, [items.length, resolvedIndex, selectIndex])

  const next = useCallback(() => {
    if (items.length <= 1) return
    selectIndex((resolvedIndex + 1) % items.length)
  }, [items.length, resolvedIndex, selectIndex])

  useLayoutEffect(() => {
    if (activeIndex >= 0) {
      if (activeIndex !== index) setIndex(activeIndex)
      return
    }

    if (items.length > 0) {
      activeItemIdRef.current = items[resolvedIndex]?.id
      if (resolvedIndex !== index) setIndex(resolvedIndex)
    }
  }, [activeIndex, index, items, resolvedIndex])

  const captureVideoFrame = useCallback(() => {
    const video = videoRef.current
    if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) {
      throw new Error('影片尚未準備好，請稍候再試')
    }

    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('無法建立圖片畫布')
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/png')
  }, [])

  const formatTimestamp = (seconds: number) => {
    if (!Number.isFinite(seconds) || seconds < 0) return '0:00.00'
    const minutes = Math.floor(seconds / 60)
    const wholeSeconds = Math.floor(seconds % 60)
    const centiseconds = Math.floor((seconds % 1) * 100)
    return `${minutes}:${wholeSeconds.toString().padStart(2, '0')}.${centiseconds.toString().padStart(2, '0')}`
  }

  const formatTimestampFine = (seconds: number) => {
    if (!Number.isFinite(seconds) || seconds < 0) return '0:00.000'
    const minutes = Math.floor(seconds / 60)
    const wholeSeconds = Math.floor(seconds % 60)
    const millis = Math.floor((seconds % 1) * 1000)
    return `${minutes}:${wholeSeconds.toString().padStart(2, '0')}.${millis.toString().padStart(3, '0')}`
  }

  const saveCurrentVideoFrame = useCallback(async () => {
    if (!item || item.media_type !== 'video' || savingFrameRef.current) return
    try {
      savingFrameRef.current = true
      onStatus?.('正在儲存目前影片畫面…')
      const timestampSeconds = scrubDraftRef.current ?? videoRef.current?.currentTime ?? videoTime
      const res = shouldUseServerFrameExtract()
        ? await api.saveVideoFrameAtTimestamp(item.path, timestampSeconds)
        : await api.saveVideoFrame(item.path, captureVideoFrame(), timestampSeconds)
      await onFrameSaved?.(res.message)
    } catch (error) {
      onStatus?.(`儲存影片畫面失敗：${error}`)
    } finally {
      savingFrameRef.current = false
    }
  }, [captureVideoFrame, item, onFrameSaved, onStatus, videoTime])

  const handleMpvReady = useCallback(() => {
    mpvReadyRef.current = true
    setMpvReady(true)
    setLoaded(true)
    mpvPausedRef.current = false
    setMpvLayoutRevision((value) => value + 1)
    void mpvGetDuration()
      .then((duration) => {
        if (Number.isFinite(duration) && duration > 0) setVideoDuration(duration)
      })
      .catch(() => {})
    void mpvGetTime()
      .then((current) => {
        if (Number.isFinite(current)) {
          lastPolledMpvTimeRef.current = current
          setVideoTime(current)
          setFineSeekCenter(current)
        }
      })
      .catch(() => {})
    window.requestAnimationFrame(() => {
      setMpvLayoutRevision((value) => value + 1)
    })
  }, [])

  const handleMpvError = useCallback((message: string) => {
    if (!item) return
    console.warn('mpv attach failed, falling back to HTML video:', message)
    mpvModeRef.current = false
    mpvReadyRef.current = false
    setMpvMode(false)
    setMpvReady(false)
    prepareStreamableVideo(item.path)
    void resolveMediaPlaybackSource(item.path).then(setVideoPlayback)
  }, [item])

  const handleClose = useCallback(() => {
    mpvReadyRef.current = false
    mpvModeRef.current = false
    setMpvReady(false)
    void mpvDetach().catch(() => {})
    onClose()
  }, [onClose])

  const toggleVideoPlayback = useCallback(() => {
    if (!item || item.media_type !== 'video' || scrubbingRef.current) return

    if (mpvModeRef.current && mpvReadyRef.current) {
      mpvPausedRef.current = !mpvPausedRef.current
      void mpvSetPaused(mpvPausedRef.current)
      return
    }

    const video = videoRef.current
    if (!video) return

    if (video.paused) {
      void video.play()
    } else {
      video.pause()
    }
  }, [item])

  const applyPlaybackSeek = useCallback((seconds: number, syncState = true) => {
    if (!mpvModeRef.current || !mpvReadyRef.current) return false
    void mpvSeek(seconds)
    if (syncState) setVideoTime(seconds)
    return true
  }, [])

  const applySeek = useCallback((
    seconds: number,
    recenter = !scrubbingRef.current,
    syncState = true,
  ) => {
    if (!item || item.media_type !== 'video') return

    const duration = videoDuration
    const nextTime = Math.min(Math.max(seconds, 0), duration || Number.POSITIVE_INFINITY)

    if (applyPlaybackSeek(nextTime, syncState)) {
      if (recenter) setFineSeekCenter(nextTime)
      return
    }

    const video = videoRef.current
    if (!video) return
    const resolvedDuration = Number.isFinite(video.duration) ? video.duration : videoDuration
    const clamped = Math.min(Math.max(seconds, 0), resolvedDuration || Number.POSITIVE_INFINITY)
    video.currentTime = clamped
    if (syncState) setVideoTime(clamped)
    if (recenter) setFineSeekCenter(clamped)
  }, [applyPlaybackSeek, item, videoDuration])

  const seekVideoTo = useCallback((seconds: number, recenter = !scrubbingRef.current) => {
    applySeek(seconds, recenter)
  }, [applySeek])

  const tryFlushPendingScrubSeek = useCallback(() => {
    if (!scrubbingRef.current) return

    const profile = scrubProfileRef.current
    if (profile.waitForSeeked && scrubSeekingRef.current) return

    const mode = scrubModeRef.current
    if (mode !== 'coarse' && mode !== 'fine') return

    const target = mode === 'fine' ? pendingFineSeekRef.current : pendingCoarseSeekRef.current
    if (target === null) return

    const video = videoRef.current
    if (!mpvModeRef.current || !mpvReadyRef.current) {
      if (!video || !item || item.media_type !== 'video') return
    } else if (!item || item.media_type !== 'video') {
      return
    }

    const baseline = lastAppliedScrubSeekRef.current
      ?? (mpvModeRef.current && mpvReadyRef.current
        ? (scrubDraftRef.current ?? videoTime)
        : (video?.currentTime ?? videoTime))
    if (Math.abs(target - baseline) < profile.minDeltaSeconds) return

    const duration = videoDuration
    const nextTime = Math.min(Math.max(target, 0), duration || Number.POSITIVE_INFINITY)
    lastAppliedScrubSeekRef.current = nextTime

    if (mpvModeRef.current && mpvReadyRef.current) {
      void mpvSeek(nextTime)
      return
    }

    if (!video) return

    if (!profile.waitForSeeked) {
      video.currentTime = nextTime
      return
    }

    const token = seekTokenRef.current + 1
    seekTokenRef.current = token
    scrubSeekingRef.current = true

    const releaseScrubSeek = () => {
      if (seekTokenRef.current !== token) return
      if (!scrubSeekingRef.current) return
      scrubSeekingRef.current = false
      if (!scrubbingRef.current) return

      const pending = scrubModeRef.current === 'fine'
        ? pendingFineSeekRef.current
        : pendingCoarseSeekRef.current
      const lastApplied = lastAppliedScrubSeekRef.current ?? nextTime
      if (
        pending !== null &&
        Math.abs(pending - lastApplied) >= scrubProfileRef.current.minDeltaSeconds
      ) {
        tryFlushPendingScrubSeek()
      }
    }

    video.addEventListener('seeked', releaseScrubSeek, { once: true })
    window.setTimeout(releaseScrubSeek, VIDEO_SEEK_SETTLE_TIMEOUT_MS)
    video.currentTime = nextTime
  }, [item, videoDuration, videoTime])

  const stopCoarsePreview = useCallback(() => {
    if (coarsePreviewTimerRef.current !== null) {
      window.clearTimeout(coarsePreviewTimerRef.current)
      coarsePreviewTimerRef.current = null
    }
    pendingCoarseSeekRef.current = null
  }, [])

  const flushCoarsePreview = useCallback(() => {
    if (!scrubbingRef.current || scrubModeRef.current !== 'coarse') return
    lastCoarsePreviewAtRef.current = performance.now()
    tryFlushPendingScrubSeek()
  }, [tryFlushPendingScrubSeek])

  const scheduleCoarsePreview = useCallback(() => {
    if (coarsePreviewTimerRef.current !== null) return
    const elapsed = performance.now() - lastCoarsePreviewAtRef.current
    const delay = Math.max(0, scrubProfileRef.current.coarsePreviewMs - elapsed)
    coarsePreviewTimerRef.current = window.setTimeout(() => {
      coarsePreviewTimerRef.current = null
      flushCoarsePreview()
    }, delay)
  }, [flushCoarsePreview])

  const stopFinePreview = useCallback(() => {
    if (finePreviewTimerRef.current !== null) {
      window.clearTimeout(finePreviewTimerRef.current)
      finePreviewTimerRef.current = null
    }
    pendingFineSeekRef.current = null
  }, [])

  const flushFinePreview = useCallback(() => {
    if (!scrubbingRef.current || scrubModeRef.current !== 'fine') return
    lastFinePreviewAtRef.current = performance.now()
    tryFlushPendingScrubSeek()
  }, [tryFlushPendingScrubSeek])

  const scheduleFinePreview = useCallback(() => {
    if (finePreviewTimerRef.current !== null) return
    const elapsed = performance.now() - lastFinePreviewAtRef.current
    const delay = Math.max(0, scrubProfileRef.current.finePreviewMs - elapsed)
    finePreviewTimerRef.current = window.setTimeout(() => {
      finePreviewTimerRef.current = null
      flushFinePreview()
    }, delay)
  }, [flushFinePreview])

  const syncScrubDraft = useCallback((seconds: number) => {
    scrubDraftRef.current = seconds
    setScrubDraftTime(seconds)
  }, [])

  const readVideoTime = useCallback(() => {
    const video = videoRef.current
    if (video && Number.isFinite(video.currentTime)) return video.currentTime
    return videoTime
  }, [videoTime])

  const startCoarseScrub = useCallback(() => {
    const video = videoRef.current
    const current = readVideoTime()
    stopCoarsePreview()
    stopFinePreview()
    if (mpvModeRef.current && mpvReadyRef.current) {
      resumeAfterScrubRef.current = !mpvPausedRef.current
      mpvPausedRef.current = true
      void mpvSetPaused(true)
    } else {
      resumeAfterScrubRef.current = Boolean(video && !video.paused)
      video?.pause()
    }
    scrubModeRef.current = 'coarse'
    setScrubMode('coarse')
    scrubbingRef.current = true
    setScrubbing(true)
    lastAppliedScrubSeekRef.current = current
    scrubDraftRef.current = current
    setScrubDraftTime(current)
    pendingCoarseSeekRef.current = current
    lastCoarsePreviewAtRef.current = 0
  }, [readVideoTime, stopCoarsePreview, stopFinePreview])

  const startFineScrub = useCallback(() => {
    const video = videoRef.current
    const current = readVideoTime()
    stopCoarsePreview()
    stopFinePreview()
    if (mpvModeRef.current && mpvReadyRef.current) {
      resumeAfterScrubRef.current = !mpvPausedRef.current
      mpvPausedRef.current = true
      void mpvSetPaused(true)
    } else {
      resumeAfterScrubRef.current = Boolean(video && !video.paused)
      video?.pause()
    }
    scrubModeRef.current = 'fine'
    setFineSeekCenter(current)
    setScrubMode('fine')
    scrubbingRef.current = true
    setScrubbing(true)
    lastAppliedScrubSeekRef.current = current
    syncScrubDraft(current)
    pendingFineSeekRef.current = current
    lastFinePreviewAtRef.current = 0
  }, [readVideoTime, stopCoarsePreview, stopFinePreview, syncScrubDraft])

  const finishScrub = useCallback((nextTime: number) => {
    if (!scrubbingRef.current) return
    seekTokenRef.current += 1
    scrubSeekingRef.current = false
    scrubbingRef.current = false
    scrubModeRef.current = null
    setScrubMode(null)
    stopCoarsePreview()
    stopFinePreview()
    setScrubbing(false)
    scrubDraftRef.current = null
    setScrubDraftTime(null)
    lastAppliedScrubSeekRef.current = null
    setFineSeekCenter(nextTime)
    applySeek(nextTime, true, true)
    if (resumeAfterScrubRef.current) {
      window.setTimeout(() => {
        if (mpvModeRef.current && mpvReadyRef.current) {
          mpvPausedRef.current = false
          void mpvSetPaused(false)
          return
        }
        void videoRef.current?.play()
      }, 80)
    }
    resumeAfterScrubRef.current = false
  }, [applySeek, stopCoarsePreview, stopFinePreview])

  const previewCoarseSeek = useCallback((seconds: number) => {
    syncScrubDraft(seconds)
    pendingCoarseSeekRef.current = seconds

    const elapsed = performance.now() - lastCoarsePreviewAtRef.current
    if (elapsed >= scrubProfileRef.current.coarsePreviewMs) {
      flushCoarsePreview()
      return
    }
    scheduleCoarsePreview()
  }, [flushCoarsePreview, scheduleCoarsePreview, syncScrubDraft])

  const handleScrubPointerMove = useCallback((
    event: React.PointerEvent<HTMLInputElement>,
    preview: (seconds: number) => void,
  ) => {
    if (event.buttons === 0) return
    preview(Number(event.currentTarget.value))
  }, [])

  const previewFineSeek = useCallback((seconds: number) => {
    syncScrubDraft(seconds)
    pendingFineSeekRef.current = seconds

    const elapsed = performance.now() - lastFinePreviewAtRef.current
    if (elapsed >= scrubProfileRef.current.finePreviewMs) {
      flushFinePreview()
      return
    }
    scheduleFinePreview()
  }, [flushFinePreview, scheduleFinePreview, syncScrubDraft])

  const seekVideo = useCallback((direction: -1 | 1, seconds: number) => {
    if (!item || item.media_type !== 'video' || seekingRef.current || scrubbingRef.current) return

    if (mpvModeRef.current && mpvReadyRef.current) {
      const duration = videoDuration > 0 ? videoDuration : Number.POSITIVE_INFINITY
      const nextTime = Math.min(Math.max(videoTime + direction * seconds, 0), duration)
      applySeek(nextTime)
      return
    }

    const video = videoRef.current
    if (!video) return

    const duration = Number.isFinite(video.duration) ? video.duration : Number.POSITIVE_INFINITY
    const nextTime = Math.min(Math.max(video.currentTime + direction * seconds, 0), duration)
    if (Math.abs(nextTime - video.currentTime) < 0.0001) return

    const token = seekTokenRef.current + 1
    seekTokenRef.current = token
    seekingRef.current = true

    let timeoutId = 0
    const releaseSeekLock = () => {
      if (seekTokenRef.current !== token) return
      window.clearTimeout(timeoutId)
      seekingRef.current = false
    }

    video.addEventListener('seeked', releaseSeekLock, { once: true })
    timeoutId = window.setTimeout(releaseSeekLock, VIDEO_SEEK_SETTLE_TIMEOUT_MS)
    video.currentTime = nextTime
    setVideoTime(nextTime)
    if (!scrubbingRef.current) setFineSeekCenter(nextTime)
  }, [applySeek, item, videoDuration, videoTime])

  const stopHoldSeek = useCallback(() => {
    if (holdSeekTimerRef.current === null) return
    window.clearInterval(holdSeekTimerRef.current)
    holdSeekTimerRef.current = null
  }, [])

  const releaseVideoControlFocus = useCallback(() => {
    const release = () => {
      videoRef.current?.blur()
      rootRef.current?.focus({ preventScroll: true })
    }
    window.setTimeout(release, 0)
    window.setTimeout(release, 80)
    window.setTimeout(release, 180)
  }, [])

  const startHoldSeek = useCallback((key: 'a' | 'd') => {
    if (holdSeekTimerRef.current !== null) return
    const direction = key === 'a' ? -1 : 1
    holdSeekTimerRef.current = window.setInterval(() => {
      seekVideo(direction, VIDEO_HOLD_SEEK_STEP_SECONDS)
    }, VIDEO_HOLD_SEEK_INTERVAL_MS)
  }, [seekVideo])

  const handleSeekKey = useCallback((key: 'a' | 'd', repeat: boolean) => {
    const direction = key === 'a' ? -1 : 1

    if (repeat) {
      startHoldSeek(key)
      return
    }

    seekVideo(direction, VIDEO_SEEK_STEP_SECONDS)
  }, [seekVideo, startHoldSeek])

  useEffect(() => {
    stopHoldSeek()
    seekingRef.current = false
    seekTokenRef.current += 1
    setVideoTime(0)
    setVideoDuration(item?.duration_seconds ?? 0)
    setFineSeekCenter(0)
    setScrubbing(false)
    setScrubMode(null)
    setScrubDraftTime(null)
    scrubbingRef.current = false
    scrubModeRef.current = null
    scrubSeekingRef.current = false
    scrubDraftRef.current = null
    lastAppliedScrubSeekRef.current = null
    resumeAfterScrubRef.current = false
    stopCoarsePreview()
    stopFinePreview()
  }, [item?.id, stopCoarsePreview, stopFinePreview, stopHoldSeek])

  useEffect(() => {
    scrubProfileRef.current = mpvMode && mpvReady
      ? getMpvScrubProfile()
      : getVideoScrubProfile(videoPlayback)
  }, [mpvMode, mpvReady, videoPlayback])

  useEffect(() => {
    if (item?.media_type !== 'video') {
      setVideoPlayback(null)
      setMpvMode(false)
      setMpvReady(false)
      setMpvProbeDone(false)
      mpvModeRef.current = false
      mpvReadyRef.current = false
      return
    }

    let cancelled = false
    setMpvReady(false)
    setMpvProbeDone(false)
    setVideoPlayback(null)
    setLoaded(false)
    setLoadError(false)
    mpvReadyRef.current = false
    mpvPausedRef.current = false

    void isNativeMpvAvailable().then((available) => {
      if (cancelled) return
      setMpvProbeDone(true)
      mpvModeRef.current = available
      setMpvMode(available)
      if (available) return
      prepareStreamableVideo(item.path)
      void resolveMediaPlaybackSource(item.path).then((source) => {
        if (!cancelled) setVideoPlayback(source)
      })
    })

    return () => {
      cancelled = true
      disposeVideoElement(videoRef.current)
      void mpvDetach().catch(() => {})
    }
  }, [item?.id, item?.media_type, item?.path])

  useEffect(() => {
    if (!playbackModeInfo || item?.media_type !== 'video') return
    console.info(`[播放診斷] ${playbackModeInfo.label} — ${playbackModeInfo.hint}`)
  }, [item?.media_type, playbackModeInfo])

  useEffect(() => {
    if (!mpvMode || !mpvReady || scrubbing) return

    const syncMpvClock = () => {
      void mpvGetTime()
        .then((current) => {
          if (!scrubbingRef.current && Number.isFinite(current)) {
            if (Math.abs(current - lastPolledMpvTimeRef.current) < 0.12) return
            lastPolledMpvTimeRef.current = current
            setVideoTime(current)
            setFineSeekCenter(current)
          }
        })
        .catch(() => {})
    }

    syncMpvClock()
    const timerId = window.setInterval(syncMpvClock, 250)
    return () => window.clearInterval(timerId)
  }, [mpvMode, mpvReady, scrubbing])

  useEffect(() => {
    const onRelease = () => {
      if (!scrubbingRef.current) return
      const next = scrubDraftRef.current ?? readVideoTime()
      finishScrub(next)
    }
    window.addEventListener('pointerup', onRelease)
    window.addEventListener('pointercancel', onRelease)
    return () => {
      window.removeEventListener('pointerup', onRelease)
      window.removeEventListener('pointercancel', onRelease)
    }
  }, [finishScrub, readVideoTime])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void saveCurrentVideoFrame()
        return
      }
      if (!e.ctrlKey && !e.metaKey && !e.altKey && e.key === ' ') {
        e.preventDefault()
        toggleVideoPlayback()
        return
      }
      if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        const key = e.key.toLowerCase()
        if (key === 'a' || key === 'd') {
          e.preventDefault()
          handleSeekKey(key, e.repeat)
          return
        }
      }
      if (e.key === 'Escape') handleClose()
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
      if (e.key === 'Enter') item && api.openPath(item.path)
    }
    const onKeyUp = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase()
      if (key === 'a' || key === 'd') stopHoldSeek()
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('keyup', onKeyUp, true)
    document.addEventListener('pointerup', releaseVideoControlFocus, true)
    document.addEventListener('mouseup', releaseVideoControlFocus, true)
    document.addEventListener('touchend', releaseVideoControlFocus, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('keyup', onKeyUp, true)
      document.removeEventListener('pointerup', releaseVideoControlFocus, true)
      document.removeEventListener('mouseup', releaseVideoControlFocus, true)
      document.removeEventListener('touchend', releaseVideoControlFocus, true)
      stopHoldSeek()
      stopCoarsePreview()
      stopFinePreview()
    }
  }, [
    handleClose,
    prev,
    next,
    item,
    saveCurrentVideoFrame,
    toggleVideoPlayback,
    handleSeekKey,
    stopHoldSeek,
    stopCoarsePreview,
    stopFinePreview,
    releaseVideoControlFocus,
  ])

  if (!item) return null

  return (
    <AnimatePresence>
      <motion.div
        ref={rootRef}
        tabIndex={-1}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex flex-col bg-black/92 outline-none"
      >
        <div className="relative z-30 flex items-center justify-between px-4 py-3 text-white">
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate">{item.name}</p>
            <p className="text-xs text-white/60">
              {resolvedIndex + 1} / {items.length} · {item.media_type === 'video' ? '影片' : '圖片'}
              {item.duration_label ? ` · ${item.duration_label}` : ''}
              {playbackModeInfo ? (
                <span
                  className={`ml-2 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium align-middle ${playbackModeBadgeClass(playbackModeInfo.tone)}`}
                  title={playbackModeInfo.hint}
                >
                  {playbackModeInfo.label}
                </span>
              ) : null}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              className="text-white hover:bg-white/10"
              onClick={() => api.openPath(item.path)}
            >
              <ExternalLink className="w-4 h-4" /> 以程式開啟
            </Button>
            <button
              type="button"
              onClick={handleClose}
              className="p-2 rounded-[var(--radius-sm)] hover:bg-white/10 text-white"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="relative flex-1 flex items-center justify-center min-h-0 px-24 py-4">
          <button
            type="button"
            onClick={prev}
            className="absolute left-0 top-0 bottom-0 w-24 flex items-center justify-center text-white/80 hover:text-white hover:bg-white/5 transition-colors z-10"
            aria-label="上一張"
          >
            <ChevronLeft className="w-10 h-10" />
          </button>

          <div className="relative w-full h-full flex items-center justify-center">
            {!loaded && !loadError && (
              <div className="absolute inset-0 flex items-center justify-center text-white/50">載入中…</div>
            )}
            {loadError ? (
              <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-white/70">
                <img
                  src={api.mediaThumbUrl(item.path, item.media_type)}
                  alt={item.name}
                  draggable={false}
                  onDragStart={(e) => e.preventDefault()}
                  className="max-h-[72vh] max-w-full rounded-[var(--radius-md)] object-contain shadow-2xl"
                  onLoad={() => setLoaded(true)}
                />
                <div className="text-center text-sm">
                  <p>無法直接載入原始檔，已改顯示預覽圖。</p>
                  <p className="mt-1 text-white/45">可按「以程式開啟」使用系統播放器或看圖工具。</p>
                </div>
              </div>
            ) : item.media_type === 'video' && mpvMode ? (
              <div className="h-full w-full min-h-0">
                <MpvVideoSurface
                  filePath={item.path}
                  active
                  layoutRevision={mpvLayoutRevision}
                  className="h-full w-full max-h-full max-w-full rounded-[var(--radius-md)] bg-black shadow-2xl"
                  onReady={handleMpvReady}
                  onError={handleMpvError}
                />
              </div>
            ) : item.media_type === 'video' && videoPlayback?.src ? (
              <motion.video
                key={item.id}
                ref={videoRef}
                initial={{ opacity: 0 }}
                animate={{ opacity: loaded ? 1 : 0 }}
                transition={{ duration: 0.2 }}
                src={videoPlayback.src}
                {...(videoPlayback.crossOrigin ? { crossOrigin: videoPlayback.crossOrigin } : {})}
                preload={playbackProfile.preload}
                className="max-w-full max-h-full rounded-[var(--radius-md)] bg-black shadow-2xl"
                controls={playbackProfile.showNativeControls}
                autoPlay
                tabIndex={-1}
                onFocus={releaseVideoControlFocus}
                onPointerUp={releaseVideoControlFocus}
                onMouseUp={releaseVideoControlFocus}
                onTouchEnd={releaseVideoControlFocus}
                onLoadedMetadata={(event) => {
                  const duration = event.currentTarget.duration
                  if (Number.isFinite(duration)) setVideoDuration(duration)
                  setLoaded(true)
                }}
                onLoadedData={(event) => {
                  setLoaded(true)
                  const current = event.currentTarget.currentTime
                  setVideoTime(current)
                  setFineSeekCenter(current)
                }}
                onPause={(event) => {
                  if (scrubbingRef.current) return
                  const current = event.currentTarget.currentTime
                  setVideoTime(current)
                  setFineSeekCenter(current)
                }}
                onCanPlay={() => setLoaded(true)}
                onTimeUpdate={(event) => {
                  if (scrubbingRef.current) return
                  const current = event.currentTarget.currentTime
                  setVideoTime(current)
                  setFineSeekCenter(current)
                }}
                onSeeked={(event) => {
                  if (scrubbingRef.current) return
                  const current = event.currentTarget.currentTime
                  setVideoTime(current)
                  setFineSeekCenter(current)
                }}
                onError={() => {
                  setLoadError(true)
                  setLoaded(true)
                }}
              />
            ) : (
              <motion.img
                key={item.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: loaded ? 1 : 0 }}
                transition={{ duration: 0.2 }}
                src={api.mediaFileUrl(item.path)}
                alt={item.name}
                draggable={false}
                onDragStart={(e) => e.preventDefault()}
                className="max-w-full max-h-full object-contain rounded-[var(--radius-md)] shadow-2xl"
                onLoad={() => setLoaded(true)}
                onError={() => {
                  setLoadError(true)
                  setLoaded(true)
                }}
              />
            )}
          </div>

          <button
            type="button"
            onClick={next}
            className="absolute right-0 top-0 bottom-0 w-24 flex items-center justify-center text-white/80 hover:text-white hover:bg-white/5 transition-colors z-10"
            aria-label="下一張"
          >
            <ChevronRight className="w-10 h-10" />
          </button>
        </div>

        {item.media_type === 'video' && !loadError && (mpvMode || mpvReady || videoPlayback?.src) && (
          <div className="relative z-30 shrink-0 px-6 pb-2 text-white">
            <div className="mx-auto flex max-w-4xl flex-col gap-2 rounded-[var(--radius-md)] border border-white/10 bg-white/5 px-4 py-2">
              <div className="flex items-center justify-between gap-3 text-xs text-white/65">
                <span>目前 {formatTimestampFine(displayedTime)}</span>
                <span>{videoDuration > 0 ? `總長 ${formatTimestamp(videoDuration)}` : '讀取時間中…'}</span>
              </div>
              {videoDuration > 0 && (
                <div className="flex items-center gap-3">
                  <span className="w-[7.5rem] shrink-0 text-[11px] leading-snug text-white/45">
                    全片時間軸（快速定位 · 連續拖拉）
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
                        startCoarseScrub()
                      }}
                      onPointerMove={(event) => handleScrubPointerMove(event, previewCoarseSeek)}
                      onPointerUp={(event) => {
                        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                          event.currentTarget.releasePointerCapture(event.pointerId)
                        }
                        finishScrub(Number(event.currentTarget.value))
                      }}
                      onPointerCancel={(event) => {
                        finishScrub(Number(event.currentTarget.value))
                      }}
                      onInput={(event) => previewCoarseSeek(Number(event.currentTarget.value))}
                      onChange={(event) => previewCoarseSeek(Number(event.currentTarget.value))}
                      className="video-scrub-range w-full"
                      aria-label="全片時間軸"
                    />
                  </div>
                </div>
              )}
              <div className="flex items-center gap-3">
                <span className="w-[7.5rem] shrink-0 text-[11px] leading-snug text-white/45">
                  精細微調（前後 {FINE_SEEK_WINDOW_SECONDS} 秒 · 毫秒級）
                </span>
                <div className="flex min-w-0 flex-1 items-center gap-2">
                <button
                  type="button"
                  onClick={() => seekVideoTo(readVideoTime() - 1)}
                  className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
                >
                  -1s
                </button>
                <button
                  type="button"
                  onClick={() => seekVideoTo(readVideoTime() - FINE_SEEK_NUDGE_SECONDS)}
                  className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
                >
                  -0.02s
                </button>
                <button
                  type="button"
                  onClick={() => seekVideoTo(readVideoTime() - FINE_SEEK_STEP_SECONDS)}
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
                      startFineScrub()
                    }}
                    onPointerMove={(event) => handleScrubPointerMove(event, previewFineSeek)}
                    onPointerUp={(event) => {
                      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                        event.currentTarget.releasePointerCapture(event.pointerId)
                      }
                      finishScrub(Number(event.currentTarget.value))
                    }}
                    onPointerCancel={(event) => {
                      finishScrub(Number(event.currentTarget.value))
                    }}
                    onInput={(event) => previewFineSeek(Number(event.currentTarget.value))}
                    onChange={(event) => previewFineSeek(Number(event.currentTarget.value))}
                    className="video-scrub-range video-scrub-range--fine w-full"
                    aria-label="精細調整影片時間"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => seekVideoTo(readVideoTime() + FINE_SEEK_STEP_SECONDS)}
                  className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
                  title="前進 1 影格（約 1/60 秒）"
                >
                  +1f
                </button>
                <button
                  type="button"
                  onClick={() => seekVideoTo(readVideoTime() + FINE_SEEK_NUDGE_SECONDS)}
                  className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
                >
                  +0.02s
                </button>
                <button
                  type="button"
                  onClick={() => seekVideoTo(readVideoTime() + 1)}
                  className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/15"
                >
                  +1s
                </button>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="px-4 py-3 border-t border-white/10 overflow-x-auto">
          <div className="flex gap-2 justify-center min-w-min">
            {items.map((m, i) => (
              <button
                key={m.id}
                type="button"
                onClick={() => {
                  selectIndex(i)
                }}
                className={`shrink-0 w-16 h-12 rounded overflow-hidden border-2 transition-colors ${
                  i === resolvedIndex ? 'border-[var(--color-accent)]' : 'border-transparent opacity-60 hover:opacity-100'
                }`}
              >
                <img
                  src={api.mediaThumbUrl(m.path, m.media_type)}
                  alt=""
                  draggable={false}
                  onDragStart={(e) => e.preventDefault()}
                  className="w-full h-full object-cover"
                />
              </button>
            ))}
          </div>
        </div>

        <p className="text-center text-xs text-white/40 pb-3">
          ← → 切換 · Enter 以外部程式開啟
          {item.media_type === 'video' ? ' · 空白鍵播放/暫停 · A/D 快退快進 · Ctrl/Cmd+S 儲存目前影片畫面' : ''} · Esc 關閉
        </p>
      </motion.div>
    </AnimatePresence>
  )
}
