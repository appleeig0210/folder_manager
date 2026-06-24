import { AnimatePresence, motion } from 'framer-motion'
import { listen } from '@tauri-apps/api/event'
import { ChevronLeft, ChevronRight, ExternalLink, Tag, X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type SyntheticEvent } from 'react'
import type { MediaItem } from '../../api/types'
import { api } from '../../api/client'
import { prepareStreamableVideo, resolveMediaImageSource, resolveMediaPlaybackSource, type MediaPlaybackSource } from '../../lib/mediaPlayback'
import { isNativeMpvAvailable, mpvDetach, mpvGetDuration, mpvGetTime, mpvRehookContextMenu, mpvSeek, mpvSetMuted, mpvSetPaused, mpvSetSurfaceVisible, mpvSetVolume } from '../../lib/mpvPlayer'
import { getMpvScrubProfile, getVideoScrubProfile, isDesktopApp, shouldProbeNativeMpv, shouldUseCustomVideoScrub, shouldUseServerFrameExtract, supportsNativeMpvEmbed, type VideoScrubProfile } from '../../lib/platform'
import { getVideoPlaybackModeInfo, playbackModeBadgeClass } from '../../lib/playbackDiagnostics'
import { isAppModalInteraction, isAppModalOpen } from '../../lib/modal'
import { WebVideoNotice } from './WebVideoNotice'
import { MpvVideoSurface } from './MpvVideoSurface'
import { disposeVideoElement } from './videoUtils'
import {
  coarseScrubProgress,
  fineScrubProgress,
  readRangeSeconds,
  shouldHandleScrubInput,
  shouldHandleScrubPointerMove,
  syncScrubRangeVisual,
} from './videoScrub'
import { Button } from '../ui/Button'
import { VideoVolumeControl } from './VideoVolumeControl'
import { clampVideoVolume, loadStoredVideoVolume, saveStoredVideoVolume } from '../../lib/videoVolume'

const VIDEO_SEEK_STEP_SECONDS = 1 / 30
const VIDEO_HOLD_SEEK_STEP_SECONDS = 1 / 60
const VIDEO_HOLD_SEEK_INTERVAL_MS = 90
const VIDEO_SEEK_SETTLE_TIMEOUT_MS = 180
const FINE_SEEK_WINDOW_SECONDS = 4
const FINE_SEEK_STEP_SECONDS = 1 / 60
const FINE_SEEK_NUDGE_SECONDS = 0.02
const MPV_REMOUNT_LIMIT = 3

interface MediaLightboxProps {
  items: MediaItem[]
  initialIndex: number
  onClose: () => void
  onStatus?: (message: string) => void
  onFrameSaved?: (message: string) => void | Promise<void>
  onContextMenu?: (e: React.MouseEvent, item: MediaItem) => void
  onAddTags?: (item: MediaItem) => void
  onMpvContextMenu?: (point: { x: number; y: number }, item: MediaItem) => void
}

type MpvContextMenuPayload = {
  x: number
  y: number
}

export function MediaLightbox({
  items,
  initialIndex,
  onClose,
  onStatus,
  onFrameSaved,
  onContextMenu,
  onAddTags,
  onMpvContextMenu,
}: MediaLightboxProps) {
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
  const [imagePlayback, setImagePlayback] = useState<MediaPlaybackSource | null>(null)
  const [imageHttpFallbackTried, setImageHttpFallbackTried] = useState(false)
  const [videoVolume, setVideoVolume] = useState(loadStoredVideoVolume)
  const [videoMuted, setVideoMuted] = useState(false)
  const [mpvMode, setMpvMode] = useState(false)
  const [mpvReady, setMpvReady] = useState(false)
  const [mpvProbeDone, setMpvProbeDone] = useState(false)
  const [mpvSurfaceKey, setMpvSurfaceKey] = useState(0)
  const [mpvRetryAttempt, setMpvRetryAttempt] = useState(0)
  const [mpvRetryMax, setMpvRetryMax] = useState(0)
  const [mpvPlaybackFailed, setMpvPlaybackFailed] = useState(false)
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
  const scrubPointerActiveRef = useRef(false)
  const activeScrubInputRef = useRef<HTMLInputElement | null>(null)
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
  const mpvRemountCountRef = useRef(0)
  const htmlFallbackTriedRef = useRef(false)
  const videoHttpFallbackTriedRef = useRef(false)
  const mpvPausedRef = useRef(false)
  const lastPolledMpvTimeRef = useRef(0)
  const [mpvLayoutRevision, setMpvLayoutRevision] = useState(0)
  const [mpvSuspendedByModal, setMpvSuspendedByModal] = useState(false)
  const [layoutReady, setLayoutReady] = useState(false)
  const layoutAttachTokenRef = useRef('')
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
  const controlDuration = videoDuration > 0 ? videoDuration : (item?.duration_seconds ?? 0)
  const coarseProgress = controlDuration > 0
    ? Math.min(100, (coarseSeekValue / controlDuration) * 100)
    : coarseSeekProgress
  const useCustomVideoScrub = shouldUseCustomVideoScrub(videoPlayback, mpvMode && mpvReady)
  const showVideoControls = item?.media_type === 'video' && !loadError && useCustomVideoScrub
  const videoPlaybackPending = item?.media_type === 'video' && !mpvMode && !videoPlayback?.src
  const playbackModeInfo = useMemo(() => {
    if (item?.media_type !== 'video') return null
    return getVideoPlaybackModeInfo({
      mpvProbeDone,
      mpvMode,
      mpvReady,
      videoPlayback,
      mpvRetryAttempt,
      mpvRetryMax,
      mpvPlaybackFailed,
    })
  }, [item?.media_type, mpvProbeDone, mpvMode, mpvReady, videoPlayback, mpvRetryAttempt, mpvRetryMax, mpvPlaybackFailed])

  const resetMpvAttachState = useCallback(() => {
    mpvRemountCountRef.current = 0
    htmlFallbackTriedRef.current = false
    setMpvPlaybackFailed(false)
    setMpvRetryAttempt(0)
    setMpvRetryMax(0)
  }, [])

  const retryMpvPlayback = useCallback(() => {
    if (!item || item.media_type !== 'video' || !supportsNativeMpvEmbed()) return
    resetMpvAttachState()
    mpvReadyRef.current = false
    mpvModeRef.current = true
    setMpvReady(false)
    setMpvMode(true)
    setVideoPlayback(null)
    setLoaded(false)
    setLoadError(false)
    void mpvDetach()
      .catch(() => {})
      .finally(() => {
        setMpvSurfaceKey((value) => value + 1)
      })
  }, [item, resetMpvAttachState])

  const selectIndex = useCallback((nextIndex: number) => {
    const nextItem = items[nextIndex]
    if (nextItem) activeItemIdRef.current = nextItem.id
    resetMpvAttachState()
    setLoaded(false)
    setLoadError(false)
    setLayoutReady(false)
    layoutAttachTokenRef.current = ''
    setIndex(nextIndex)
  }, [items, resetMpvAttachState])

  const prev = useCallback(() => {
    if (items.length <= 1) return
    selectIndex((resolvedIndex - 1 + items.length) % items.length)
  }, [items.length, resolvedIndex, selectIndex])

  const next = useCallback(() => {
    if (items.length <= 1) return
    selectIndex((resolvedIndex + 1) % items.length)
  }, [items.length, resolvedIndex, selectIndex])

  useLayoutEffect(() => {
    activeItemIdRef.current = items[initialIndex]?.id
    setIndex(initialIndex)
    setLayoutReady(false)
    layoutAttachTokenRef.current = ''
  }, [initialIndex])

  useLayoutEffect(() => {
    const preservedId = activeItemIdRef.current
    if (preservedId) {
      const nextIndex = items.findIndex((candidate) => candidate.id === preservedId)
      if (nextIndex >= 0) {
        if (nextIndex !== index) setIndex(nextIndex)
        return
      }
    }
    if (items.length > 0) {
      const fallback = Math.min(Math.max(0, initialIndex), items.length - 1)
      activeItemIdRef.current = items[fallback]?.id
      if (fallback !== index) setIndex(fallback)
    }
  }, [items, initialIndex, index])

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
    mpvRemountCountRef.current = 0
    htmlFallbackTriedRef.current = false
    mpvReadyRef.current = true
    setMpvReady(true)
    setLoaded(true)
    setMpvPlaybackFailed(false)
    setMpvRetryAttempt(0)
    setMpvRetryMax(0)
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
    // mpv creates its render child window slightly after IPC is ready, so re-install
    // the right-click hooks a few times to make sure the video surface is covered.
    for (const delay of [0, 250, 700, 1500]) {
      window.setTimeout(() => {
        void mpvRehookContextMenu().catch(() => {})
      }, delay)
    }
  }, [])

  const handleMpvRetry = useCallback((attempt: number, maxAttempts: number) => {
    setMpvRetryAttempt(attempt)
    setMpvRetryMax(maxAttempts)
  }, [])

  const handleMpvError = useCallback((message: string) => {
    if (!item) return
    console.warn('mpv attach failed:', message)

    if (mpvRemountCountRef.current < MPV_REMOUNT_LIMIT) {
      mpvRemountCountRef.current += 1
      mpvReadyRef.current = false
      setMpvReady(false)
      setLoaded(false)
      void mpvDetach()
        .catch(() => {})
        .finally(() => {
          setMpvSurfaceKey((value) => value + 1)
        })
      return
    }

    if (!htmlFallbackTriedRef.current && supportsNativeMpvEmbed()) {
      htmlFallbackTriedRef.current = true
      mpvModeRef.current = false
      mpvReadyRef.current = false
      setMpvMode(false)
      setMpvReady(false)
      prepareStreamableVideo(item.path)
      void resolveMediaPlaybackSource(item.path).then(setVideoPlayback)
      return
    }

    setMpvPlaybackFailed(true)
    setLoaded(true)
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

  const applyVideoVolume = useCallback((volume: number, muted: boolean) => {
    const clamped = clampVideoVolume(volume)
    if (mpvModeRef.current && mpvReadyRef.current) {
      void mpvSetMuted(muted)
      if (!muted) void mpvSetVolume(Math.round(clamped * 100))
    }
    const video = videoRef.current
    if (video) {
      video.muted = muted
      video.volume = clamped
    }
  }, [])

  const changeVideoVolume = useCallback((nextVolume: number) => {
    const clamped = clampVideoVolume(nextVolume)
    setVideoVolume(clamped)
    saveStoredVideoVolume(clamped)
    if (clamped > 0) {
      setVideoMuted(false)
      applyVideoVolume(clamped, false)
      return
    }
    setVideoMuted(true)
    applyVideoVolume(clamped, true)
  }, [applyVideoVolume])

  const toggleVideoMute = useCallback(() => {
    setVideoMuted((prev) => {
      const next = !prev
      applyVideoVolume(videoVolume, next)
      return next
    })
  }, [applyVideoVolume, videoVolume])

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
    scrubPointerActiveRef.current = false
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
    if (activeScrubInputRef.current) {
      activeScrubInputRef.current.blur()
      activeScrubInputRef.current = null
    }
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

  const previewCoarseSeek = useCallback((seconds: number, input?: HTMLInputElement | null) => {
    syncScrubDraft(seconds)
    if (input) {
      syncScrubRangeVisual(input, coarseScrubProgress(seconds, videoDuration))
    }
    pendingCoarseSeekRef.current = seconds

    const elapsed = performance.now() - lastCoarsePreviewAtRef.current
    if (elapsed >= scrubProfileRef.current.coarsePreviewMs) {
      flushCoarsePreview()
      return
    }
    scheduleCoarsePreview()
  }, [flushCoarsePreview, scheduleCoarsePreview, syncScrubDraft, videoDuration])

  const handleScrubPointerMove = useCallback((
    event: React.PointerEvent<HTMLInputElement>,
    preview: (seconds: number, input: HTMLInputElement) => void,
  ) => {
    if (!shouldHandleScrubPointerMove(event, scrubPointerActiveRef.current)) return
    preview(readRangeSeconds(event), event.currentTarget)
  }, [])

  const endScrubFromInput = useCallback((
    event: { currentTarget: HTMLInputElement; pointerId?: number },
  ) => {
    if (!scrubbingRef.current) return
    if (
      event.pointerId !== undefined &&
      event.currentTarget.hasPointerCapture(event.pointerId)
    ) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    finishScrub(readRangeSeconds(event))
  }, [finishScrub])

  const previewFineSeek = useCallback((seconds: number, input?: HTMLInputElement | null) => {
    syncScrubDraft(seconds)
    if (input) {
      syncScrubRangeVisual(input, fineScrubProgress(seconds, fineSeekStart, fineSeekEnd))
    }
    pendingFineSeekRef.current = seconds

    const elapsed = performance.now() - lastFinePreviewAtRef.current
    if (elapsed >= scrubProfileRef.current.finePreviewMs) {
      flushFinePreview()
      return
    }
    scheduleFinePreview()
  }, [fineSeekEnd, fineSeekStart, flushFinePreview, scheduleFinePreview, syncScrubDraft])

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

  const releaseVideoControlFocus = useCallback((event?: Event | SyntheticEvent) => {
    const nativeEvent = event && 'nativeEvent' in event ? event.nativeEvent : event
    if (isAppModalInteraction(nativeEvent)) return
    const release = () => {
      if (isAppModalOpen()) return
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
    setLoadError(false)
    scrubbingRef.current = false
    scrubPointerActiveRef.current = false
    scrubModeRef.current = null
    scrubSeekingRef.current = false
    scrubDraftRef.current = null
    lastAppliedScrubSeekRef.current = null
    resumeAfterScrubRef.current = false
    activeScrubInputRef.current = null
    stopCoarsePreview()
    stopFinePreview()
  }, [item?.id, stopCoarsePreview, stopFinePreview, stopHoldSeek])

  useEffect(() => {
    scrubProfileRef.current = mpvMode && mpvReady
      ? getMpvScrubProfile()
      : getVideoScrubProfile(videoPlayback)
  }, [mpvMode, mpvReady, videoPlayback])

  useEffect(() => {
    if (item?.media_type !== 'video') return
    applyVideoVolume(videoVolume, videoMuted)
  }, [applyVideoVolume, item?.id, mpvReady, videoMuted, videoPlayback?.src, videoVolume])

  useEffect(() => {
    const onOpen = () => {
      setMpvSuspendedByModal(true)
      void mpvDetach().catch(() => {})
    }
    const onClose = () => {
      setMpvSuspendedByModal(false)
      setMpvSurfaceKey((value) => value + 1)
    }
    window.addEventListener('app-modal-open', onOpen)
    window.addEventListener('app-modal-close', onClose)
    return () => {
      window.removeEventListener('app-modal-open', onOpen)
      window.removeEventListener('app-modal-close', onClose)
    }
  }, [])

  useEffect(() => {
    if (item?.media_type !== 'video') {
      setLayoutReady(true)
      return
    }
    const fallbackId = window.setTimeout(() => {
      setLayoutReady(true)
    }, 320)
    return () => window.clearTimeout(fallbackId)
  }, [item?.id, item?.media_type])

  useEffect(() => {
    if (item?.media_type !== 'video') {
      setVideoPlayback(null)
      setMpvMode(false)
      setMpvReady(false)
      setMpvProbeDone(false)
      mpvModeRef.current = false
      mpvReadyRef.current = false
      resetMpvAttachState()
      return
    }

    let cancelled = false
    resetMpvAttachState()
    setMpvReady(false)
    setMpvProbeDone(false)
    setVideoPlayback(null)
    videoHttpFallbackTriedRef.current = false
    setLoaded(false)
    setLoadError(false)
    setMpvSurfaceKey((value) => value + 1)
    mpvReadyRef.current = false
    mpvPausedRef.current = false

    const setupPlayback = async () => {
      await mpvDetach().catch(() => {})
      if (cancelled) return

      if (!shouldProbeNativeMpv()) {
        setMpvProbeDone(true)
        setMpvMode(false)
        mpvModeRef.current = false
        prepareStreamableVideo(item.path)
        const source = await resolveMediaPlaybackSource(item.path)
        if (!cancelled) setVideoPlayback(source)
        return
      }

      const available = await isNativeMpvAvailable()
      if (cancelled) return
      setMpvProbeDone(true)
      mpvModeRef.current = available
      setMpvMode(available)
      if (available) return
      prepareStreamableVideo(item.path)
      const source = await resolveMediaPlaybackSource(item.path)
      if (!cancelled) setVideoPlayback(source)
    }

    void setupPlayback()

    return () => {
      cancelled = true
      disposeVideoElement(videoRef.current)
      void mpvDetach().catch(() => {})
    }
  }, [item?.id, item?.media_type, item?.path, resetMpvAttachState])

  useEffect(() => {
    if (item?.media_type === 'video') {
      setImagePlayback(null)
      setImageHttpFallbackTried(false)
      return
    }

    let cancelled = false
    setImagePlayback(null)
    setImageHttpFallbackTried(false)
    setLoaded(false)
    setLoadError(false)

    void resolveMediaImageSource(item?.path ?? '').then((source) => {
      if (!cancelled) setImagePlayback(source)
    })

    return () => {
      cancelled = true
    }
  }, [item?.id, item?.media_type, item?.path])

  useEffect(() => {
    if (item?.media_type !== 'video') return
    if (mpvMode || videoPlayback?.src) {
      setLoadError(false)
    }
  }, [item?.media_type, mpvMode, videoPlayback?.src])

  useEffect(() => {
    if (!playbackModeInfo || item?.media_type !== 'video') return
    console.info(`[播放診斷] ${playbackModeInfo.label} — ${playbackModeInfo.hint}`)
  }, [item?.media_type, playbackModeInfo])

  useEffect(() => {
    if (!mpvMode || !onMpvContextMenu || item?.media_type !== 'video') return
    let disposed = false
    let unlisten: (() => void) | undefined

    void listen<MpvContextMenuPayload>('mpv-context-menu', (event) => {
      if (disposed || !mpvModeRef.current || !mpvReadyRef.current || !item) return
      const scale = window.devicePixelRatio || 1
      void mpvSetSurfaceVisible(false).catch(() => {})
      onMpvContextMenu(
        {
          x: event.payload.x / scale,
          y: event.payload.y / scale,
        },
        item,
      )
    }).then((dispose) => {
      if (disposed) {
        dispose()
        return
      }
      unlisten = dispose
    })

    return () => {
      disposed = true
      unlisten?.()
    }
  }, [item, item?.media_type, mpvMode, onMpvContextMenu])

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
    if (!layoutReady || mpvSuspendedByModal || !mpvMode || mpvReady || item?.media_type !== 'video') return
    const token = `${item.id}:layout`
    if (layoutAttachTokenRef.current === token) return
    layoutAttachTokenRef.current = token
    setMpvSurfaceKey((value) => value + 1)
  }, [item?.id, item?.media_type, layoutReady, mpvMode, mpvReady, mpvSuspendedByModal])

  useEffect(() => {
    if (!mpvMode || !mpvReady || videoDuration > 0) return
    let cancelled = false
    const syncDuration = () => {
      void mpvGetDuration()
        .then((duration) => {
          if (!cancelled && Number.isFinite(duration) && duration > 0) {
            setVideoDuration(duration)
          }
        })
        .catch(() => {})
    }
    syncDuration()
    const retryId = window.setTimeout(syncDuration, 250)
    const retryId2 = window.setTimeout(syncDuration, 900)
    return () => {
      cancelled = true
      window.clearTimeout(retryId)
      window.clearTimeout(retryId2)
    }
  }, [item?.id, mpvMode, mpvReady, videoDuration])

  useEffect(() => {
    const onRelease = () => {
      if (!scrubbingRef.current) return
      const next = scrubDraftRef.current ?? readVideoTime()
      finishScrub(next)
    }
    document.addEventListener('pointerup', onRelease, true)
    document.addEventListener('pointercancel', onRelease, true)
    document.addEventListener('mouseup', onRelease, true)
    return () => {
      document.removeEventListener('pointerup', onRelease, true)
      document.removeEventListener('pointercancel', onRelease, true)
      document.removeEventListener('mouseup', onRelease, true)
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
      if (e.key === 'Escape') {
        if (isAppModalOpen()) return
        handleClose()
      }
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

  const handlePreviewContextMenu = (e: React.MouseEvent) => {
    if (!onContextMenu) return
    e.preventDefault()
    e.stopPropagation()
    onContextMenu(e, item)
  }

  return (
    <AnimatePresence>
      <motion.div
        ref={rootRef}
        tabIndex={-1}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onAnimationComplete={() => setLayoutReady(true)}
        className="fixed inset-0 z-50 flex flex-col bg-black/92 outline-none"
      >
        <div
          className="relative z-30 flex items-center justify-between px-4 py-3 text-white"
          onContextMenu={handlePreviewContextMenu}
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5 min-w-0">
              {item.tags.length > 0 ? (
                item.tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex max-w-[12rem] truncate px-2.5 py-0.5 rounded-[var(--radius-pill)] text-xs font-medium border bg-[var(--color-panel-2)] text-[var(--color-text-muted)] border-[var(--color-border)]"
                    title={tag}
                  >
                    {tag}
                  </span>
                ))
              ) : (
                <span className="text-xs text-white/45 shrink-0">（尚未標籤）</span>
              )}
            </div>
          </div>
          <div className="pointer-events-none absolute left-1/2 top-1/2 z-0 flex max-w-[40%] -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center">
            <p className="text-sm font-semibold truncate max-w-full">{item.name}</p>
            <p className="text-xs text-white/60 mt-0.5">
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
            {onAddTags ? (
              <Button
                size="sm"
                variant="ghost"
                className="text-white hover:bg-white/10"
                onClick={() => onAddTags(item)}
              >
                <Tag className="w-4 h-4" /> 標籤
              </Button>
            ) : onContextMenu ? (
              <Button
                size="sm"
                variant="ghost"
                className="text-white hover:bg-white/10"
                onClick={handlePreviewContextMenu}
              >
                <Tag className="w-4 h-4" /> 標籤
              </Button>
            ) : null}
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

          <div
            className="relative w-full h-full flex items-center justify-center"
            onContextMenu={handlePreviewContextMenu}
          >
            {((!loaded && !loadError && !(item.media_type === 'video' && mpvPlaybackFailed))
              || videoPlaybackPending
              || (item.media_type !== 'video' && !loadError && !imagePlayback?.src)) && (
              <div className="absolute inset-0 flex items-center justify-center text-white/50">
                {item.media_type === 'video' && mpvMode && mpvRetryAttempt > 0
                  ? `mpv 重試中 (${mpvRetryAttempt}/${mpvRetryMax})…`
                  : '載入中…'}
              </div>
            )}
            {loadError && item.media_type !== 'video' ? (
              <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-white/70">
                <img
                  src={api.mediaThumbUrl(item.path, item.media_type)}
                  alt={item.name}
                  draggable={false}
                  onDragStart={(e) => e.preventDefault()}
                  onContextMenu={handlePreviewContextMenu}
                  className="max-h-[72vh] max-w-full rounded-[var(--radius-md)] object-contain shadow-2xl"
                  onLoad={() => setLoaded(true)}
                />
                <div className="text-center text-sm">
                  <p>無法直接載入原始檔，已改顯示預覽圖。</p>
                  <p className="mt-1 text-white/45">可按「以程式開啟」使用系統播放器或看圖工具。</p>
                </div>
              </div>
            ) : item.media_type === 'video' && mpvMode ? (
              <div className="relative h-full w-full min-h-0" onContextMenu={handlePreviewContextMenu}>
                <MpvVideoSurface
                  key={`${item.id}:${mpvSurfaceKey}`}
                  filePath={item.path}
                  active={layoutReady && !mpvSuspendedByModal}
                  layoutRevision={mpvLayoutRevision}
                  className="h-full w-full max-h-full max-w-full rounded-[var(--radius-md)] bg-black shadow-2xl"
                  onReady={handleMpvReady}
                  onError={handleMpvError}
                  onRetry={handleMpvRetry}
                />
                {mpvPlaybackFailed && supportsNativeMpvEmbed() ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-[var(--radius-md)] bg-black/80 text-white/80">
                    <p className="text-sm">mpv 無法嵌入此影片，可重試或改用系統播放器。</p>
                    <Button size="sm" variant="secondary" onClick={retryMpvPlayback}>
                      重試 mpv
                    </Button>
                  </div>
                ) : null}
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
                onContextMenu={handlePreviewContextMenu}
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
                  if (supportsNativeMpvEmbed()) {
                    retryMpvPlayback()
                    return
                  }
                  if (videoPlayback?.via === 'asset' && !videoHttpFallbackTriedRef.current) {
                    videoHttpFallbackTriedRef.current = true
                    prepareStreamableVideo(item.path)
                    setVideoPlayback({
                      src: api.mediaFileUrl(item.path),
                      crossOrigin: 'anonymous',
                      via: 'http',
                    })
                    setLoadError(false)
                    setLoaded(false)
                    return
                  }
                  setLoadError(true)
                  setLoaded(true)
                }}
              />
            ) : item.media_type === 'video' ? null : imagePlayback?.src ? (
              <motion.img
                key={`${item.id}:${imagePlayback.via}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: loaded ? 1 : 0 }}
                transition={{ duration: 0.2 }}
                src={imagePlayback.src}
                alt={item.name}
                draggable={false}
                onDragStart={(e) => e.preventDefault()}
                onContextMenu={handlePreviewContextMenu}
                className="max-w-full max-h-full object-contain rounded-[var(--radius-md)] shadow-2xl"
                onLoad={() => setLoaded(true)}
                onError={() => {
                  if (imagePlayback?.via === 'asset' && !imageHttpFallbackTried) {
                    setImageHttpFallbackTried(true)
                    setImagePlayback({ src: api.mediaFileUrl(item.path), via: 'http' })
                    setLoadError(false)
                    setLoaded(false)
                    return
                  }
                  setLoadError(true)
                  setLoaded(true)
                }}
              />
            ) : null}
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

        {showVideoControls && (
          <div className="relative z-30 shrink-0 px-6 pb-2 text-white" onContextMenu={handlePreviewContextMenu}>
            {!isDesktopApp() ? <WebVideoNotice /> : null}
            <div className="mx-auto flex max-w-4xl flex-col gap-2 rounded-[var(--radius-md)] border border-white/10 bg-white/5 px-4 py-2">
              <div className="flex items-center justify-between gap-3 text-xs text-white/65">
                <span>目前 {formatTimestampFine(displayedTime)}</span>
                <span>{controlDuration > 0 ? `總長 ${formatTimestamp(controlDuration)}` : '讀取時間中…'}</span>
              </div>
              {controlDuration > 0 && (
                <div className="flex items-center gap-3">
                  <span className="w-[7.5rem] shrink-0 text-[11px] leading-snug text-white/45">
                    全片時間軸
                  </span>
                  <div className="video-scrub-range-wrap min-w-0 flex-1">
                    <div className="video-scrub-range-track" aria-hidden>
                      <div
                        className="video-scrub-range-fill video-scrub-range-fill--coarse"
                        style={{ width: `${coarseProgress}%` }}
                      />
                    </div>
                    <div
                      className="video-scrub-range-thumb"
                      style={{ '--scrub-progress': coarseProgress / 100 } as CSSProperties}
                      aria-hidden
                    />
                    <input
                      type="range"
                      min={0}
                      max={Math.max(videoDuration, controlDuration)}
                      step="any"
                      value={Math.min(coarseSeekValue, Math.max(videoDuration, controlDuration) || coarseSeekValue)}
                      onPointerDown={(event) => {
                        event.currentTarget.setPointerCapture(event.pointerId)
                        activeScrubInputRef.current = event.currentTarget
                        scrubPointerActiveRef.current = true
                        startCoarseScrub()
                      }}
                      onPointerMove={(event) => handleScrubPointerMove(event, previewCoarseSeek)}
                      onPointerUp={endScrubFromInput}
                      onPointerCancel={endScrubFromInput}
                      onMouseUp={endScrubFromInput}
                      onLostPointerCapture={endScrubFromInput}
                      onInput={(event) => {
                        if (!shouldHandleScrubInput(scrubPointerActiveRef.current)) return
                        previewCoarseSeek(readRangeSeconds(event), event.currentTarget)
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
                      activeScrubInputRef.current = event.currentTarget
                      scrubPointerActiveRef.current = true
                      startFineScrub()
                    }}
                    onPointerMove={(event) => handleScrubPointerMove(event, previewFineSeek)}
                    onPointerUp={endScrubFromInput}
                    onPointerCancel={endScrubFromInput}
                    onMouseUp={endScrubFromInput}
                    onLostPointerCapture={endScrubFromInput}
                    onInput={(event) => {
                      if (!shouldHandleScrubInput(scrubPointerActiveRef.current)) return
                      previewFineSeek(readRangeSeconds(event), event.currentTarget)
                    }}
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
                <VideoVolumeControl
                  className="ml-1 w-[6.5rem] shrink-0 border-l border-white/10 pl-2"
                  volume={videoVolume}
                  muted={videoMuted}
                  onVolumeChange={changeVideoVolume}
                  onToggleMute={toggleVideoMute}
                  showPercent={false}
                />
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="px-4 py-3 border-t border-white/10 overflow-x-auto" onContextMenu={handlePreviewContextMenu}>
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
          {item.media_type === 'video' ? ' · 空白鍵播放/暫停 · A/D 快退快進 · Ctrl/Cmd+S 儲存目前影片畫面' : ''}
          {item.media_type === 'video' && mpvMode ? ' · mpv 播放區請用上方「標籤」或時間軸右鍵' : ''} · Esc 關閉
        </p>
      </motion.div>
    </AnimatePresence>
  )
}
