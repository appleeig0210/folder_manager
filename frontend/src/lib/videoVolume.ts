export const VIDEO_VOLUME_STORAGE_KEY = 'people-folder-manager-video-volume'

export const DEFAULT_VIDEO_VOLUME = 0.85

export function clampVideoVolume(volume: number): number {
  if (!Number.isFinite(volume)) return DEFAULT_VIDEO_VOLUME
  return Math.min(1, Math.max(0, volume))
}

export function loadStoredVideoVolume(): number {
  try {
    const raw = window.localStorage.getItem(VIDEO_VOLUME_STORAGE_KEY)
    if (raw === null) return DEFAULT_VIDEO_VOLUME
    return clampVideoVolume(Number(raw))
  } catch {
    return DEFAULT_VIDEO_VOLUME
  }
}

export function saveStoredVideoVolume(volume: number): void {
  try {
    window.localStorage.setItem(VIDEO_VOLUME_STORAGE_KEY, String(clampVideoVolume(volume)))
  } catch {
    // ignore storage failures
  }
}
