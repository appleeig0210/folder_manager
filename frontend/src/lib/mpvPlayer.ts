import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { shouldProbeNativeMpv } from './platform'

export type MpvBounds = {
  x: number
  y: number
  width: number
  height: number
}

export async function isNativeMpvAvailable(): Promise<boolean> {
  if (!shouldProbeNativeMpv()) return false
  try {
    return await invoke<boolean>('mpv_is_available')
  } catch {
    return false
  }
}

export async function waitForMpvSurfaceLayout(element: HTMLElement, timeoutMs = 3000): Promise<void> {
  const deadline = performance.now() + timeoutMs
  while (performance.now() < deadline) {
    const rect = element.getBoundingClientRect()
    if (rect.width > 0 && rect.height > 0) return
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  }
  throw new Error('mpv surface has zero size')
}

export async function measureMpvBounds(element: HTMLElement): Promise<MpvBounds> {
  await waitForMpvSurfaceLayout(element)
  const rect = element.getBoundingClientRect()
  const window = getCurrentWindow()
  const factor = await window.scaleFactor()
  // getBoundingClientRect is webview-local; convert to physical pixels for Win32 child HWND.
  return {
    x: Math.round(rect.left * factor),
    y: Math.round(rect.top * factor),
    width: Math.max(1, Math.round(rect.width * factor)),
    height: Math.max(1, Math.round(rect.height * factor)),
  }
}

export async function mpvAttach(path: string, bounds: MpvBounds): Promise<void> {
  await invoke('mpv_attach', {
    path,
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
  })
}

export async function mpvSetBounds(bounds: MpvBounds): Promise<void> {
  await invoke('mpv_set_bounds', {
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
  })
}

export async function mpvSeek(seconds: number): Promise<void> {
  await invoke('mpv_seek', { seconds })
}

export async function mpvSetPaused(paused: boolean): Promise<void> {
  await invoke('mpv_set_paused', { paused })
}

export async function mpvGetTime(): Promise<number> {
  return invoke<number>('mpv_get_time')
}

export async function mpvGetDuration(): Promise<number> {
  return invoke<number>('mpv_get_duration')
}

export async function mpvDetach(): Promise<void> {
  await invoke('mpv_detach')
}
