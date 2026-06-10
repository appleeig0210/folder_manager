import { cn } from '../../lib/utils'
import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md'
}

const variants: Record<Variant, string> = {
  primary: 'bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] shadow-sm',
  secondary: 'bg-[var(--color-panel-2)] text-[var(--color-text)] border border-[var(--color-border)] hover:bg-[var(--color-border)]',
  ghost: 'bg-transparent text-[var(--color-text-muted)] hover:bg-[var(--color-panel-2)] hover:text-[var(--color-text)]',
  danger: 'bg-[var(--color-danger)] text-white hover:opacity-90',
}

export function Button({ variant = 'secondary', size = 'md', className, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-sm)] font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none',
        size === 'sm' ? 'h-8 px-3 text-xs' : 'h-9 px-4 text-sm',
        variants[variant],
        className,
      )}
      {...props}
    />
  )
}
