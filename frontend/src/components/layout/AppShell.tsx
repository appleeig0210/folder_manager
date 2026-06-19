import { FolderOpen, Moon, PanelLeftClose, PanelLeftOpen, RefreshCw, Sun, Upload, Download } from 'lucide-react'
import type { ReactNode } from 'react'
import { Breadcrumb } from '../navigation/Breadcrumb'
import type { BreadcrumbItem } from '../../api/types'
import { Button } from '../ui/Button'
import { cn } from '../../lib/utils'

interface AppShellProps {
  children: ReactNode
  sidebar: ReactNode
  breadcrumb: BreadcrumbItem[]
  scopeLabel: string
  status: string
  rootFolder: string
  sidebarOpen: boolean
  darkMode: boolean
  onToggleSidebar: () => void
  onToggleTheme: () => void
  onNavigate: (path: string) => void
  onChooseFolder: () => void
  onRefresh: () => void
  onImportTags: () => void
  onExportTags: () => void
  platformLabel?: string
}

export function AppShell({
  children,
  sidebar,
  breadcrumb,
  scopeLabel,
  status,
  rootFolder,
  sidebarOpen,
  darkMode,
  onToggleSidebar,
  onToggleTheme,
  onNavigate,
  onChooseFolder,
  onRefresh,
  onImportTags,
  onExportTags,
  platformLabel,
}: AppShellProps) {
  return (
    <div className="h-full flex flex-col bg-[var(--color-bg)]">
      <header className="shrink-0 flex items-center gap-3 px-4 h-14 border-b border-[var(--color-border)] bg-[var(--color-panel)] shadow-[var(--shadow-sm)]">
        <button
          type="button"
          onClick={onToggleSidebar}
          className="p-2 rounded-[var(--radius-sm)] text-[var(--color-text-muted)] hover:bg-[var(--color-panel-2)]"
        >
          {sidebarOpen ? <PanelLeftClose className="w-5 h-5" /> : <PanelLeftOpen className="w-5 h-5" />}
        </button>
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-8 h-8 rounded-[var(--radius-sm)] bg-[var(--color-accent)] flex items-center justify-center text-white">
            <FolderOpen className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-[var(--color-text)] truncate">人物資料夾管理器</h1>
            <p className="text-xs text-[var(--color-text-muted)] truncate max-w-[320px]" title={rootFolder || '未設定主資料夾'}>
              {rootFolder || '未設定主資料夾'}
            </p>
          </div>
        </div>
        <div className="hidden md:flex flex-1 min-w-0 px-4">
          <Breadcrumb items={breadcrumb} onNavigate={onNavigate} />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button size="sm" variant="primary" onClick={onChooseFolder}>
            選擇資料夾
          </Button>
          <Button size="sm" onClick={onRefresh}>
            <RefreshCw className="w-4 h-4" />
          </Button>
          <Button size="sm" onClick={onImportTags}>
            <Upload className="w-4 h-4" />
          </Button>
          <Button size="sm" onClick={onExportTags}>
            <Download className="w-4 h-4" />
          </Button>
          <button
            type="button"
            onClick={onToggleTheme}
            className="p-2 rounded-[var(--radius-sm)] text-[var(--color-text-muted)] hover:bg-[var(--color-panel-2)]"
          >
            {darkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </header>

      <div className="flex-1 flex min-h-0">
        <aside
          className={cn(
            'shrink-0 border-r border-[var(--color-border)] bg-[var(--color-panel)] transition-all overflow-hidden flex flex-col',
            sidebarOpen ? 'w-64' : 'w-0',
          )}
        >
          <div className="px-3 py-2 text-xs font-semibold text-[var(--color-text-muted)] border-b border-[var(--color-border)]">
            導覽樹狀欄位
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">{sidebar}</div>
        </aside>
        <main className="flex-1 flex flex-col min-w-0 min-h-0">{children}</main>
      </div>

      <footer className="shrink-0 flex items-center justify-between px-4 h-9 border-t border-[var(--color-border)] bg-[var(--color-panel)] text-xs text-[var(--color-text-muted)]">
        <span className="truncate">{status}</span>
        <div className="ml-4 flex min-w-0 items-center gap-3">
          {platformLabel ? <span className="shrink-0">{platformLabel}</span> : null}
          <span className="truncate">{scopeLabel}</span>
        </div>
      </footer>
    </div>
  )
}
