import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { isTauriRuntime } from '../../lib/utils'
import { InputDialog } from './InputDialog'

type TextPromptOptions = {
  title: string
  description?: string
  defaultValue?: string
  placeholder?: string
  confirmLabel?: string
}

type PendingPrompt = TextPromptOptions & {
  resolve: (value: string | null) => void
}

type TextPromptContextValue = {
  promptText: (options: TextPromptOptions) => Promise<string | null>
  confirmAction: (message: string) => Promise<boolean>
}

const TextPromptContext = createContext<TextPromptContextValue | null>(null)

export function TextPromptProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingPrompt | null>(null)

  const promptText = useCallback((options: TextPromptOptions) => {
    if (!isTauriRuntime()) {
      const value = window.prompt(options.title, options.defaultValue ?? '')
      return Promise.resolve(value)
    }
    return new Promise<string | null>((resolve) => {
      setPending({ ...options, resolve })
    })
  }, [])

  const confirmAction = useCallback(async (message: string) => {
    if (!isTauriRuntime()) {
      return window.confirm(message)
    }
    const { confirm } = await import('@tauri-apps/plugin-dialog')
    return confirm(message, { title: '確認', kind: 'warning' })
  }, [])

  const value = useMemo(
    () => ({
      promptText,
      confirmAction,
    }),
    [confirmAction, promptText],
  )

  return (
    <TextPromptContext.Provider value={value}>
      {children}
      {pending ? (
        <InputDialog
          title={pending.title}
          description={pending.description}
          defaultValue={pending.defaultValue}
          placeholder={pending.placeholder}
          confirmLabel={pending.confirmLabel}
          onSubmit={(value) => {
            pending.resolve(value)
            setPending(null)
          }}
          onCancel={() => {
            pending.resolve(null)
            setPending(null)
          }}
        />
      ) : null}
    </TextPromptContext.Provider>
  )
}

export function useTextPrompt(): TextPromptContextValue {
  const ctx = useContext(TextPromptContext)
  if (!ctx) {
    throw new Error('useTextPrompt must be used within TextPromptProvider')
  }
  return ctx
}
