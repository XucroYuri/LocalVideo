import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { ReferenceLibraryItem, StageReferenceImportResult } from '@/types/reference'

interface ScriptReferenceImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  importSettingChecked: boolean
  onImportSettingCheckedChange: (checked: boolean) => void
  importAppearanceChecked: boolean
  onImportAppearanceCheckedChange: (checked: boolean) => void
  importImageChecked: boolean
  onImportImageCheckedChange: (checked: boolean) => void
  importVoiceChecked: boolean
  onImportVoiceCheckedChange: (checked: boolean) => void
  selectedImportCount: number
  libraryReferences: ReferenceLibraryItem[]
  onSelectAll: () => void
  onClearAll: () => void
  importStartReferenceIndex: number
  overwriteReferencePreview: Array<{ name?: string }>
  appendCountPreview: number
  importSelectionOrder: number[]
  onToggleImportSelection: (libraryReferenceId: number, checked: boolean) => void
  importResult: StageReferenceImportResult | null
  isImportingReferences: boolean
  onConfirm: () => void
}

export function ScriptReferenceImportDialog(props: ScriptReferenceImportDialogProps) {
  const {
    open,
    onOpenChange,
    importSettingChecked,
    onImportSettingCheckedChange,
    importAppearanceChecked,
    onImportAppearanceCheckedChange,
    importImageChecked,
    onImportImageCheckedChange,
    importVoiceChecked,
    onImportVoiceCheckedChange,
    selectedImportCount,
    libraryReferences,
    onSelectAll,
    onClearAll,
    importStartReferenceIndex,
    overwriteReferencePreview,
    appendCountPreview,
    importSelectionOrder,
    onToggleImportSelection,
    importResult,
    isImportingReferences,
    onConfirm,
  } = props

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>从已有参考导入</DialogTitle>
          <DialogDescription>
            参考名称与&ldquo;是否可说台词&rdquo;会固定导入；其余字段可按需勾选。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <div className="text-sm font-medium">导入字段</div>
            <div className="rounded-md border p-3 space-y-2 text-sm">
              <div className="text-muted-foreground">固定导入：参考名称、是否可说台词</div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={importSettingChecked}
                  onChange={(e) => onImportSettingCheckedChange(e.target.checked)}
                />
                <span>参考设定</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={importAppearanceChecked}
                  onChange={(e) => onImportAppearanceCheckedChange(e.target.checked)}
                />
                <span>参考外观描述</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={importImageChecked}
                  onChange={(e) => onImportImageCheckedChange(e.target.checked)}
                />
                <span>参考图片</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={importVoiceChecked}
                  onChange={(e) => onImportVoiceCheckedChange(e.target.checked)}
                />
                <span>声音</span>
              </label>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">选择导入对象（{selectedImportCount}/{libraryReferences.length}）</div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={onSelectAll}>
                  全选
                </Button>
                <Button variant="outline" size="sm" onClick={onClearAll}>
                  清空
                </Button>
              </div>
            </div>
            <div className="rounded-md border p-3 text-xs text-muted-foreground space-y-1">
              <div>导入起始位置：第 {importStartReferenceIndex + 1} 个角色</div>
              {overwriteReferencePreview.length > 0 ? (
                <div>
                  将覆盖：
                  {overwriteReferencePreview
                    .map((ref, idx) => `#${importStartReferenceIndex + idx + 1} ${ref.name || '未命名参考'}`)
                    .join('、')}
                </div>
              ) : (
                <div>将覆盖：无</div>
              )}
              <div>将新增：{appendCountPreview} 个角色</div>
            </div>
            <div className="rounded-md border max-h-64 overflow-y-auto">
              {libraryReferences.length === 0 ? (
                <div className="p-3 text-sm text-muted-foreground">参考库为空，请先去顶部导航中的&ldquo;参考库&rdquo;创建。</div>
              ) : (
                <div className="divide-y">
                  {libraryReferences.map((item) => {
                    const selectionIndex = importSelectionOrder.indexOf(item.id)
                    const isSelected = selectionIndex >= 0
                    return (
                      <label
                        key={item.id}
                        className="flex items-center justify-between gap-3 p-3 cursor-pointer hover:bg-accent/40"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span
                            className={cn(
                              'inline-flex h-5 min-w-5 items-center justify-center rounded border px-1 text-[11px]',
                              isSelected
                                ? 'border-primary bg-primary text-primary-foreground'
                                : 'border-muted-foreground/30 text-muted-foreground'
                            )}
                            aria-hidden="true"
                          >
                            {isSelected ? selectionIndex + 1 : ''}
                          </span>
                          <input
                            type="checkbox"
                            className="sr-only"
                            checked={isSelected}
                            onChange={(e) => onToggleImportSelection(item.id, e.target.checked)}
                          />
                          <span className="text-sm truncate">{item.name}</span>
                        </div>
                        <span className="text-xs text-muted-foreground flex-shrink-0">
                          {item.can_speak ? '可说台词' : '不可说台词'}
                          {item.image_file_path ? ' · 含图片' : ''}
                        </span>
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          {importResult && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="text-sm font-medium">
                导入结果：成功 {importResult.summary.created_count}，跳过 {importResult.summary.skipped_count}，失败 {importResult.summary.failed_count}
              </div>
              <div className="max-h-44 overflow-y-auto space-y-2">
                {importResult.results.map((item, idx) => (
                  <div key={`${item.library_reference_id}-${idx}`} className="text-xs bg-muted/40 rounded p-2">
                    <div className="font-medium">
                      [{item.status}] {item.library_name || `#${item.library_reference_id}`} - {item.message}
                    </div>
                    {item.warnings.length > 0 && (
                      <div className="text-muted-foreground mt-1">
                        警告：{item.warnings.join('，')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isImportingReferences}>
            关闭
          </Button>
          <Button onClick={onConfirm} disabled={isImportingReferences || libraryReferences.length === 0}>
            {isImportingReferences ? '导入中...' : '开始导入'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
