import { FolderInput, Pencil, Tag, Trash2 } from 'lucide-react'
import { Button } from '../ui/Button'

interface SelectionToolbarProps {
  count: number
  onTransfer: () => void
  onRenameNumbered: () => void
  onAddTags: () => void
  onDelete: () => void
}

export function SelectionToolbar({ count, onTransfer, onRenameNumbered, onAddTags, onDelete }: SelectionToolbarProps) {
  if (count === 0) return null
  return (
    <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-40 flex items-center gap-2 px-4 py-2 rounded-[var(--radius-md)] bg-[var(--color-panel)]/95 border border-[var(--color-border)] shadow-[0_18px_48px_rgba(15,23,42,0.22),0_4px_12px_rgba(15,23,42,0.12)] backdrop-blur">
      <span className="text-sm font-medium text-[var(--color-text)] mr-2">已選 {count} 項</span>
      <Button size="sm" variant="ghost" onClick={onAddTags}>
        <Tag className="w-4 h-4" /> 標籤
      </Button>
      <Button size="sm" variant="ghost" onClick={onTransfer}>
        <FolderInput className="w-4 h-4" /> 轉移
      </Button>
      <Button size="sm" variant="ghost" onClick={onRenameNumbered}>
        <Pencil className="w-4 h-4" /> 序號命名
      </Button>
      <Button size="sm" variant="danger" onClick={onDelete}>
        <Trash2 className="w-4 h-4" /> 刪除
      </Button>
    </div>
  )
}
