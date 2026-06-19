import type { MediaPlaybackSource } from './mediaPlayback'
import { isDesktopApp, WEB_LIMITATIONS } from './platform'

export type VideoPlaybackMode =
  | 'detecting'
  | 'mpv-connecting'
  | 'mpv'
  | 'asset'
  | 'http'
  | 'web-http'

export type VideoPlaybackModeInfo = {
  mode: VideoPlaybackMode
  label: string
  hint: string
  tone: 'neutral' | 'success' | 'info' | 'warn'
}

export function getVideoPlaybackModeInfo(input: {
  mpvProbeDone: boolean
  mpvMode: boolean
  mpvReady: boolean
  videoPlayback: MediaPlaybackSource | null
}): VideoPlaybackModeInfo {
  const { mpvProbeDone, mpvMode, mpvReady, videoPlayback } = input

  if (!mpvProbeDone) {
    return {
      mode: 'detecting',
      label: '偵測中',
      hint: '正在檢查 mpv 與播放來源',
      tone: 'neutral',
    }
  }

  if (mpvMode && mpvReady) {
    return {
      mode: 'mpv',
      label: 'mpv 內嵌',
      hint: 'B2：原生 mpv，不經 HTTP 串流',
      tone: 'success',
    }
  }

  if (mpvMode && !mpvReady) {
    return {
      mode: 'mpv-connecting',
      label: 'mpv 連線中',
      hint: 'B2：正在嵌入 mpv 播放器',
      tone: 'info',
    }
  }

  if (videoPlayback?.via === 'asset') {
    return {
      mode: 'asset',
      label: '本地 asset',
      hint: 'A：Tauri asset:// 本機播放',
      tone: 'info',
    }
  }

  if (videoPlayback?.via === 'http') {
    if (isDesktopApp()) {
      return {
        mode: 'http',
        label: 'HTTP 串流',
        hint: 'fallback：終端可能出現 /api/thumbnails/file',
        tone: 'warn',
      }
    }
    return {
      mode: 'web-http',
      label: '網頁 HTTP',
      hint: WEB_LIMITATIONS.note,
      tone: 'warn',
    }
  }

  return {
    mode: 'detecting',
    label: '載入中',
    hint: '正在準備播放來源',
    tone: 'neutral',
  }
}

export function playbackModeBadgeClass(tone: VideoPlaybackModeInfo['tone']): string {
  switch (tone) {
    case 'success':
      return 'border-emerald-400/40 bg-emerald-500/15 text-emerald-200'
    case 'info':
      return 'border-sky-400/40 bg-sky-500/15 text-sky-200'
    case 'warn':
      return 'border-amber-400/40 bg-amber-500/15 text-amber-200'
    default:
      return 'border-white/15 bg-white/8 text-white/70'
  }
}
