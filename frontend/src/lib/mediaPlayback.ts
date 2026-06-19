import { api } from '../api/client'
import { isTauriRuntime } from './utils'

export type MediaPlaybackSource = {
  src: string
  crossOrigin?: 'anonymous'
  via: 'asset' | 'http'
}

export async function resolveMediaPlaybackSource(filePath: string): Promise<MediaPlaybackSource> {
  if (isTauriRuntime()) {
    try {
      const { convertFileSrc } = await import('@tauri-apps/api/core')
      return { src: convertFileSrc(filePath), via: 'asset' }
    } catch {
      // Fall back to HTTP when asset protocol is unavailable.
    }
  }

  return {
    src: api.mediaFileUrl(filePath),
    crossOrigin: 'anonymous',
    via: 'http',
  }
}

export function prepareStreamableVideo(path: string): void {
  if (isTauriRuntime()) return
  void api.prepareStreamableVideo(path).catch(() => {})
}
