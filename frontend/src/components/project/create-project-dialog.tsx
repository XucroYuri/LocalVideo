'use client'

import { useState } from 'react'
import { Loader2, Sparkles, Mic2, Film } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { ProjectVideoType } from '@/types/project'

interface CreateProjectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreateProject: (params: {
    video_mode: 'oral_script_driven' | 'audio_visual_driven'
    video_type: ProjectVideoType
  }) => Promise<void>
}

const ORAL_PRESET_OPTIONS: Array<{ type: ProjectVideoType; label: string; description: string }> = [
  { type: 'single_narration', label: '单人叙述', description: '单角色叙事表达，强调观点与节奏。' },
  { type: 'duo_podcast', label: '双人播客', description: '默认一镜到底，自动创建双讲述者与播客场景。' },
  { type: 'dialogue_script', label: '台词剧本', description: '多角色台词结构，适合戏剧化推进。' },
]

export function CreateProjectDialog({
  open,
  onOpenChange,
  onCreateProject,
}: CreateProjectDialogProps) {
  const [creatingType, setCreatingType] = useState<ProjectVideoType | null>(null)

  const handleCreate = async (videoType: ProjectVideoType) => {
    if (creatingType) return
    setCreatingType(videoType)
    try {
      await onCreateProject({
        video_mode: 'oral_script_driven',
        video_type: videoType,
      })
      onOpenChange(false)
    } finally {
      setCreatingType(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !creatingType && onOpenChange(nextOpen)}>
      <DialogContent className="!w-[96vw] sm:!max-w-[900px] max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>选择项目模式</DialogTitle>
          <DialogDescription>
            先选择视频创作模式，再进入对应工作流。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 md:grid-cols-2">
          <Card className="border-primary/40">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Mic2 className="h-4 w-4" />
                口播文案驱动
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                文案和音频是核心，视频围绕台词结构与表达节奏生成。
              </p>
              <Button
                className="w-full"
                disabled={creatingType !== null}
                onClick={() => void handleCreate('custom')}
              >
                {creatingType === 'custom' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                创建自定义项目
              </Button>
              <p className="text-xs text-muted-foreground">
                自定义模式不预设角色/文案约束，可自由调整角色与台词结构。
              </p>
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">快速预设</div>
                <div className="space-y-2">
                  {ORAL_PRESET_OPTIONS.map((preset) => (
                    <button
                      key={preset.type}
                      type="button"
                      className="w-full rounded-md border px-3 py-2 text-left hover:bg-muted/50 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                      onClick={() => void handleCreate(preset.type)}
                      disabled={creatingType !== null}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{preset.label}</span>
                        {creatingType === preset.type ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{preset.description}</p>
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="opacity-70">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Film className="h-4 w-4" />
                声画驱动
                <Badge variant="secondary">暂未支持</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                以画面表达力与情绪冲击为核心，语言仅作为辅助表达。
              </p>
              <Button className="w-full" variant="outline" disabled>
                <Sparkles className="mr-2 h-4 w-4" />
                功能开发中
              </Button>
            </CardContent>
          </Card>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={creatingType !== null}
          >
            取消
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
