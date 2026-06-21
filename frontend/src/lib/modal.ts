export const APP_MODAL_SELECTOR = '[data-app-modal]'

export function isAppModalOpen(): boolean {
  return Boolean(document.querySelector(APP_MODAL_SELECTOR))
}

export function isAppModalInteraction(event?: Event | null): boolean {
  const target = event?.target
  if (target instanceof Element && target.closest(APP_MODAL_SELECTOR)) {
    return true
  }
  const active = document.activeElement
  if (active instanceof Element && active.closest(APP_MODAL_SELECTOR)) {
    return true
  }
  return isAppModalOpen()
}

export function notifyAppModalOpen(): void {
  window.dispatchEvent(new CustomEvent('app-modal-open'))
}

export function notifyAppModalClose(): void {
  window.dispatchEvent(new CustomEvent('app-modal-close'))
}
