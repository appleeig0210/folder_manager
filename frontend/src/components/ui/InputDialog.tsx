import { useEffect, useRef } from 'react'
import { Button } from './Button'

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

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <form
        className="w-full max-w-[460px] rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-panel)] p-5 shadow-[var(--shadow-md)]"
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit(inputRef.current?.value ?? '')
        }}
      >
        <h2 className="text-base font-semibold text-[var(--color-text)]">{title}</h2>
        {description ? (
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">{description}</p>
        ) : null}
        <input
          ref={inputRef}
          type="text"
          defaultValue={defaultValue}
          placeholder={placeholder}
          className="mt-4 w-full rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
        />
        <div className="mt-5 flex justify-end gap-2">
          <Button size="sm" variant="ghost" type="button" onClick={onCancel}>
            取消
          </Button>
          <Button size="sm" variant="primary" type="submit">
            {confirmLabel}
          </Button>
        </div>
      </form>
    </div>
  )
}
