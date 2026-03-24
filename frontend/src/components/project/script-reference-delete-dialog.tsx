import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface ScriptReferenceDeleteDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  referenceName: string
  isDeleting: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ScriptReferenceDeleteDialog(props: ScriptReferenceDeleteDialogProps) {
  const {
    open,
    onOpenChange,
    referenceName,
    isDeleting,
    onCancel,
    onConfirm,
  } = props

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>确认删除参考</DialogTitle>
          <DialogDescription>
            确定要删除参考「{referenceName}」吗？此操作不可撤销，该参考将不会用于后续的视频生成。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isDeleting}>
            取消
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={isDeleting}>
            {isDeleting ? '删除中...' : '确认删除'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
