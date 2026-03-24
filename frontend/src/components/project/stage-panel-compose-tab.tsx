import { useMemo } from 'react'

import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  COMPOSE_CANVAS_STRATEGY_OPTIONS,
  COMPOSE_FIXED_ASPECT_RATIO_OPTIONS,
  estimateComposeCanvas,
  formatAspectRatio,
  getComposeFixedResolutionOptions,
} from '@/lib/compose-canvas'
import type { StageConfig } from '@/types/stage-panel'

interface StagePanelComposeTabProps {
  config: StageConfig
  updateConfig: (updates: Partial<StageConfig>) => void
  videoShots: Array<{ width?: number; height?: number }>
  effectiveComposeVideoFitMode: 'truncate' | 'scale' | 'none'
  isSingleTakeEnabled: boolean
  sectionTitleClass: string
}

export function StagePanelComposeTab(props: StagePanelComposeTabProps) {
  const {
    config,
    updateConfig,
    videoShots,
    effectiveComposeVideoFitMode,
    isSingleTakeEnabled,
    sectionTitleClass,
  } = props
  const composeCanvasStrategy = config.composeCanvasStrategy || 'max_size'
  const fixedAspectRatio = config.composeFixedAspectRatio || '9:16'
  const fixedResolutionOptions = useMemo(
    () => getComposeFixedResolutionOptions(fixedAspectRatio),
    [fixedAspectRatio]
  )
  const fixedResolution = (
    fixedResolutionOptions.some((item) => item.value === config.composeFixedResolution)
      ? config.composeFixedResolution
      : fixedResolutionOptions[0]?.value
  ) || '1080x1920'
  const selectedStrategy = COMPOSE_CANVAS_STRATEGY_OPTIONS.find(
    (item) => item.value === composeCanvasStrategy
  ) || COMPOSE_CANVAS_STRATEGY_OPTIONS[0]
  const canvasEstimate = useMemo(() => estimateComposeCanvas({
    strategy: composeCanvasStrategy,
    videoItems: videoShots,
    fixedResolution,
  }), [composeCanvasStrategy, fixedResolution, videoShots])

  return (
    <div className="space-y-4">
      <h4 className={sectionTitleClass}>视频合成</h4>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label>视频时长适应音频</Label>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] text-muted-foreground hover:text-foreground"
                aria-label="视频时长适应说明"
              >
                ?
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">
              <div className="text-xs leading-relaxed max-w-[260px]">
                会在后台自动给每段视频补少量尾部冗余，避免音频末尾贴边或出现无声空白。
                当视频时长不足时，会自动拉长到目标时长；当视频已足够长时，仍按下方选项处理。
              </div>
            </TooltipContent>
          </Tooltip>
        </div>
        <Select
          value={effectiveComposeVideoFitMode}
          onValueChange={(v) => updateConfig({ videoFitMode: v as 'truncate' | 'scale' | 'none' })}
          disabled={isSingleTakeEnabled}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="truncate">截断</SelectItem>
            <SelectItem value="scale">缩放</SelectItem>
            <SelectItem value="none">不适应（保持原始视频长度）</SelectItem>
          </SelectContent>
        </Select>
        {isSingleTakeEnabled && (
          <p className="text-xs text-amber-600">一镜到底模式下已强制为「缩放」，避免分镜衔接断档。</p>
        )}
      </div>

      <div className="space-y-2">
        <Label>视频拼接方式</Label>
        <Select
          value={composeCanvasStrategy}
          onValueChange={(value) => updateConfig({
            composeCanvasStrategy: value as 'max_size' | 'most_common' | 'first_shot' | 'fixed',
          })}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {COMPOSE_CANVAS_STRATEGY_OPTIONS.map((item) => (
              <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">{selectedStrategy.description}</p>
        {canvasEstimate ? (
          <p className="text-xs text-muted-foreground">
            当前预计最终分辨率：{canvasEstimate.width}x{canvasEstimate.height}
            {' '}({formatAspectRatio(canvasEstimate.width, canvasEstimate.height)})
            {' '}· {canvasEstimate.sourceLabel}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            当前还没有可用的分镜视频尺寸；生成分镜后会在这里显示预计最终分辨率。
          </p>
        )}
      </div>

      {composeCanvasStrategy === 'fixed' && (
        <>
          <div className="space-y-2">
            <Label>固定目标宽高比</Label>
            <Select
              value={fixedAspectRatio}
              onValueChange={(value) => {
                const nextOptions = getComposeFixedResolutionOptions(value)
                updateConfig({
                  composeFixedAspectRatio: value,
                  composeFixedResolution: nextOptions[0]?.value || '',
                })
              }}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {COMPOSE_FIXED_ASPECT_RATIO_OPTIONS.map((item) => (
                  <SelectItem key={item} value={item}>{item}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              固定目标宽高比后，所有分镜都会先等比缩放，再补边到这个统一画布。
            </p>
          </div>

          <div className="space-y-2">
            <Label>固定目标分辨率</Label>
            <Select
              value={fixedResolution}
              onValueChange={(value) => updateConfig({ composeFixedResolution: value })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {fixedResolutionOptions.map((item) => (
                  <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              这里只提供常见输出尺寸，避免最终视频被放大到过于激进的分辨率。
            </p>
          </div>
        </>
      )}

      <div className="flex items-center space-x-2 pt-1">
        <Checkbox
          id="includeSubtitle"
          checked={config.includeSubtitle ?? true}
          onCheckedChange={(checked) => updateConfig({ includeSubtitle: !!checked })}
        />
        <Label htmlFor="includeSubtitle" className="cursor-pointer">加入字幕</Label>
      </div>

      {(config.includeSubtitle ?? true) && (
        <>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>字幕字号</Label>
              <span className="text-xs text-muted-foreground">{config.subtitleFontSize ?? 15}px</span>
            </div>
            <Slider
              value={[config.subtitleFontSize ?? 15]}
              onValueChange={(v) => updateConfig({ subtitleFontSize: v[0] })}
              min={6}
              max={20}
              step={1}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>字幕垂直位置</Label>
              <span className="text-xs text-muted-foreground">
                {Math.round(config.subtitlePositionPercent ?? 80)}%
              </span>
            </div>
            <Slider
              value={[config.subtitlePositionPercent ?? 80]}
              onValueChange={(v) => updateConfig({ subtitlePositionPercent: v[0] })}
              min={0}
              max={100}
              step={1}
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>顶部 (0)</span>
              <span>底部 (100)</span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
