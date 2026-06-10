import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Windows「複製為路徑」常會帶引號，需先清掉再送後端。 */
export function normalizeFolderPath(raw: string): string {
  return raw.trim().replace(/^["']|["']$/g, '')
}

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
}
