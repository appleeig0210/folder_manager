type TauriWindow = Window & {
  __TAURI_INTERNALS__?: unknown
}

export function isTauriRuntime() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in (window as TauriWindow)
}

function createDragPreviewIcon(count: number) {
  const canvas = document.createElement('canvas')
  const scale = window.devicePixelRatio || 1
  const size = 56
  canvas.width = size * scale
  canvas.height = size * scale

  const ctx = canvas.getContext('2d')
  if (!ctx) {
    return 'data:image/png;base64,'
  }

  ctx.scale(scale, scale)
  ctx.clearRect(0, 0, size, size)

  ctx.fillStyle = 'rgba(79, 70, 229, 0.18)'
  ctx.strokeStyle = 'rgba(79, 70, 229, 0.35)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.roundRect(14, 10, 34, 36, 9)
  ctx.fill()
  ctx.stroke()

  ctx.fillStyle = 'rgba(255, 255, 255, 0.96)'
  ctx.strokeStyle = 'rgba(79, 70, 229, 0.65)'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.roundRect(8, 6, 36, 40, 10)
  ctx.fill()
  ctx.stroke()

  ctx.fillStyle = '#4f46e5'
  ctx.beginPath()
  ctx.roundRect(15, 16, 22, 5, 3)
  ctx.roundRect(15, 25, 22, 5, 3)
  ctx.roundRect(15, 34, 16, 5, 3)
  ctx.fill()

  if (count > 1) {
    ctx.fillStyle = '#111827'
    ctx.beginPath()
    ctx.arc(43, 42, 11, 0, Math.PI * 2)
    ctx.fill()

    ctx.fillStyle = '#ffffff'
    ctx.font = '700 12px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(Math.min(count, 99)), 43, 42)
  }

  return canvas.toDataURL('image/png')
}

export async function startNativeFileDrag(paths: string[]) {
  if (!paths.length || !isTauriRuntime()) {
    return false
  }

  const { startDrag } = await import('@crabnebula/tauri-plugin-drag')
  await startDrag({ item: paths, icon: createDragPreviewIcon(paths.length), mode: 'copy' })
  return true
}
