import type { MediaPlaybackSource } from './mediaPlayback'
import { isTauriRuntime } from './utils'

export type AppPlatform = 'desktop' | 'web'

export type VideoScrubProfile = {
  coarsePreviewMs: number
  finePreviewMs: number
  minDeltaSeconds: number
  waitForSeeked: boolean
  preload: 'auto' | 'metadata'
  showNativeControls: boolean
}

/** 桌面版完整能力（主要產品路徑） */
export const DESKTOP_FEATURES = {
  nativeDialogs: true,
  nativeFileDrag: true,
  mpvEmbed: true,
  assetPlayback: true,
  ffmpegFrameExtract: true,
  videoPipeline: 'mpv → asset → http',
} as const

/** 瀏覽器版刻意閹割的能力 */
export const WEB_LIMITATIONS = {
  nativeDialogs: false,
  nativeFileDrag: false,
  mpvEmbed: false,
  assetPlayback: false,
  ffmpegFrameExtract: false,
  videoPipeline: 'http-only',
  note: '請使用桌面版（npm run tauri:dev）以獲得完整影片拖動、原生對話框與檔案拖出。',
} as const

const WEB_SCRUB_PROFILE: VideoScrubProfile = {
  coarsePreviewMs: 150,
  finePreviewMs: 150,
  minDeltaSeconds: 0.1,
  waitForSeeked: true,
  preload: 'metadata',
  showNativeControls: true,
}

const DESKTOP_LOCAL_SCRUB_PROFILE: VideoScrubProfile = {
  coarsePreviewMs: 50,
  finePreviewMs: 40,
  minDeltaSeconds: 0.03,
  waitForSeeked: false,
  preload: 'auto',
  showNativeControls: false,
}

/** macOS WKWebView 的 asset 播放 seek 需更頻繁同步，避免受控 range 與影片時間打架。 */
const DESKTOP_MAC_ASSET_SCRUB_PROFILE: VideoScrubProfile = {
  coarsePreviewMs: 16,
  finePreviewMs: 16,
  minDeltaSeconds: 0.008,
  waitForSeeked: false,
  preload: 'auto',
  showNativeControls: false,
}

const DESKTOP_HTTP_SCRUB_PROFILE: VideoScrubProfile = {
  coarsePreviewMs: 100,
  finePreviewMs: 100,
  minDeltaSeconds: 0.06,
  waitForSeeked: true,
  preload: 'metadata',
  showNativeControls: false,
}

const DESKTOP_MPV_SCRUB_PROFILE: VideoScrubProfile = {
  coarsePreviewMs: 32,
  finePreviewMs: 24,
  minDeltaSeconds: 0.01,
  waitForSeeked: false,
  preload: 'auto',
  showNativeControls: false,
}

export function getAppPlatform(): AppPlatform {
  return isTauriRuntime() ? 'desktop' : 'web'
}

export function isDesktopApp(): boolean {
  return getAppPlatform() === 'desktop'
}

export function getPlatformLabel(): string {
  return isDesktopApp() ? '桌面版' : '瀏覽器（功能受限）'
}

export function getRecommendedDevCommand(): string {
  return 'npm run tauri:dev'
}

export function supportsMpvEmbed(): boolean {
  return isDesktopApp()
}

export function supportsAssetPlayback(): boolean {
  return isDesktopApp()
}

export function supportsNativeFileDrag(): boolean {
  return isDesktopApp()
}

export function shouldProbeNativeMpv(): boolean {
  return supportsMpvEmbed()
}

function isMacDesktopApp(): boolean {
  if (!isDesktopApp()) return false
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent)
}

export function getVideoScrubProfile(playback: MediaPlaybackSource | null): VideoScrubProfile {
  if (!isDesktopApp()) return WEB_SCRUB_PROFILE
  if (playback?.via === 'asset') {
    return isMacDesktopApp() ? DESKTOP_MAC_ASSET_SCRUB_PROFILE : DESKTOP_LOCAL_SCRUB_PROFILE
  }
  return DESKTOP_HTTP_SCRUB_PROFILE
}

export function shouldUseServerFrameExtract(): boolean {
  return isDesktopApp()
}

export function getMpvScrubProfile(): VideoScrubProfile {
  return DESKTOP_MPV_SCRUB_PROFILE
}
