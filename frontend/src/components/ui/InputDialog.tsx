import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from './Button'
import { notifyAppModalClose, notifyAppModalOpen } from '../../lib/modal'
import { shouldProbeNativeMpv } from '../../lib/platform'

interface InputDialogProps {
  title: string
  description?: string
  defaultValue?: string
  placeholder?: string
  confirmLabel?: string
  onSubmit: (value: string) => void
  onCancel: () => void
}

export function InputDialog({
  title,
  description,
  defaultValue = '',
  placeholder,
  confirmLabel = '確定',
  onSubmit,
  onCancel,
}: InputDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const composingRef = useRef(false)
  const [value, setValue] = useState(defaultValue)

  useEffect(() => {
    let cancelled = false
    if (shouldProbeNativeMpv()) {
      void import('../../lib/mpvPlayer').then(({ mpvDetach }) => {
        if (!cancelled) void mpvDetach().catch(() => {})
      })
    }
    notifyAppModalOpen()
    const focusInput = () => {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
    focusInput()
    const id = window.requestAnimationFrame(focusInput)
    return () => {
      window.cancelAnimationFrame(id)
      if (!cancelled) notifyAppModalClose()
      cancelled = true
    }
  }, [])

  const submitValue = useCallback(() => {
    if (composingRef.current) return
    const next = (inputRef.current?.value ?? value).trim()
    onSubmit(next)
  }, [onSubmit, value])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        e.preventDefault()
        onCancel()
        return
      }
      if (e.key === 'Enter' && !e.isComposing && document.activeElement === inputRef.current) {
        e.preventDefault()
        submitValue()
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [onCancel, submitValue])

  return (
    <div
      data-app-modal
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <form
        className="w-full max-w-[460px] rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-panel)] p-5 shadow-[var(--shadow-md)]"
        onMouseDown={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault()
          submitValue()
        }}
      >
        <h2 className="text-base font-semibold text-[var(--color-text)]">{title}</h2>
        {description ? (
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">{description}</p>
        ) : null}
        <input
          ref={inputRef}
          type="text"
          value={value}
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onCompositionStart={() => {
            composingRef.current = true
          }}
          onCompositionEnd={(e) => {
            composingRef.current = false
            setValue(e.currentTarget.value)
          }}
          className="mt-4 w-full rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
        />
        <div className="mt-5 flex justify-end gap-2">
          <Button size="sm" variant="ghost" type="button" onClick={onCancel}>
            取消
          </Button>
          <Button
            size="sm"
            variant="primary"
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={submitValue}
          >
            {confirmLabel}
          </Button>
        </div>
      </form>
    </div>
  )
}
