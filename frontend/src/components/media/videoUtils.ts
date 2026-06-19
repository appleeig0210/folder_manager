/** Release decoder buffers and abort in-flight media fetches. */
export function disposeVideoElement(video: HTMLVideoElement | null): void {
  if (!video) return
  video.pause()
  video.removeAttribute('src')
  video.load()
}
