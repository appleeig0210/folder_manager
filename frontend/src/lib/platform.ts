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

const DESKTOP_HTTP_SCRUB_PROFILE: VideoScrubProfile = {
  coarsePreviewMs: 100,
  finePreviewMs: 100,
  minDeltaSeconds: 0.06,
  waitForSeeked: true,
  preload: 'metadata',
  showNativeControls: false,
}

export function getAppPlatform(): AppPlatform {
  return isTauriRuntime() ? 'desktop' : 'web'
}

export function isDesktopApp(): boolean {
  return getAppPlatform() === 'desktop'
}

export function getVideoScrubProfile(playback: MediaPlaybackSource | null): VideoScrubProfile {
  if (!isDesktopApp()) return WEB_SCRUB_PROFILE
  if (playback?.via === 'asset') return DESKTOP_LOCAL_SCRUB_PROFILE
  return DESKTOP_HTTP_SCRUB_PROFILE
}

export function shouldUseServerFrameExtract(): boolean {
  return isDesktopApp()
}

const DESKTOP_MPV_SCRUB_PROFILE: VideoScrubProfile = {
  coarsePreviewMs: 32,
  finePreviewMs: 24,
  minDeltaSeconds: 0.01,
  waitForSeeked: false,
  preload: 'auto',
  showNativeControls: false,
}

export function getMpvScrubProfile(): VideoScrubProfile {
  return DESKTOP_MPV_SCRUB_PROFILE
}
