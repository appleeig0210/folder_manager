import { api } from '../api/client'
import { isDesktopApp } from './platform'

export type MediaPlaybackSource = {
  src: string
  crossOrigin?: 'anonymous'
  via: 'asset' | 'http'
}

async function resolveAssetSource(filePath: string): Promise<MediaPlaybackSource | null> {
  if (!isDesktopApp()) return null
  try {
    const { convertFileSrc } = await import('@tauri-apps/api/core')
    return { src: convertFileSrc(filePath), via: 'asset' }
  } catch {
    return null
  }
}

export async function resolveMediaPlaybackSource(filePath: string): Promise<MediaPlaybackSource> {
  const asset = await resolveAssetSource(filePath)
  if (asset) return asset

  return {
    src: api.mediaFileUrl(filePath),
    crossOrigin: 'anonymous',
    via: 'http',
  }
}

export async function resolveMediaImageSource(filePath: string): Promise<MediaPlaybackSource> {
  const asset = await resolveAssetSource(filePath)
  if (asset) return asset

  return {
    src: api.mediaFileUrl(filePath),
    via: 'http',
  }
}

export function prepareStreamableVideo(path: string): void {
  if (isDesktopApp()) return
  void api.prepareStreamableVideo(path).catch(() => {})
}
