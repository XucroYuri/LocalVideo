'use client'

import { Cpu, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Settings, SettingsUpdate } from '@/types/settings'
import { RuntimeValidationBadge } from './settings-runtime-validation-badge'

interface SettingsLocalModelDependencySectionProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  onValidateWan2gp: () => void
  isValidatingWan2gp: boolean
}

export function SettingsLocalModelDependencySection(props: SettingsLocalModelDependencySectionProps) {
  const {
    settings,
    formData,
    updateField,
    onValidateWan2gp,
    isValidatingWan2gp,
  } = props
  const deploymentProfile = (formData.deployment_profile ?? settings?.deployment_profile ?? 'cpu').trim()
  const isContainerizedRuntime = Boolean(settings?.is_containerized_runtime)

  if (deploymentProfile !== 'gpu') {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-5 w-5" />
            本地模型依赖
          </CardTitle>
          <CardDescription>当前为 CPU 部署，本地模型依赖 Wan2GP 已禁用</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cpu className="h-5 w-5" />
          本地模型依赖
        </CardTitle>
        <CardDescription>管理本地 Wan2GP 与 GPU fast-whisper 共用依赖</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-3 rounded-lg border p-3">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-medium">Wan2GP</p>
            <RuntimeValidationBadge status={settings?.wan2gp_validation_status} />
          </div>
          <p className="text-xs text-muted-foreground">
            首次预览或正式生成时，Wan2GP 可能会先初始化并下载一批通用共享模型
            （例如 `pose`、`depth`、`flow` 等），这是 Wan2GP 运行时的正常初始化行为。
          </p>
          <div className="space-y-2">
            <Label htmlFor="wan2gp_path">路径</Label>
            <Input
              id="wan2gp_path"
              placeholder="/path/to/Wan2GP"
              value={formData.wan2gp_path ?? settings?.wan2gp_path ?? ''}
              onChange={(e) => updateField('wan2gp_path', e.target.value)}
              disabled={isContainerizedRuntime}
            />
            <p className="text-xs text-muted-foreground">
              用于本地 Wan2GP 能力接入（需包含 `wgp.py`）。
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="local_model_python_path">共享 Python 路径</Label>
            <Input
              id="local_model_python_path"
              placeholder="/path/to/envs/local-model/bin/python"
              value={formData.local_model_python_path ?? settings?.local_model_python_path ?? ''}
              onChange={(e) => updateField('local_model_python_path', e.target.value)}
              disabled={isContainerizedRuntime}
            />
            <p className="text-xs text-muted-foreground">
              用于 Wan2GP 与 fast-whisper (GPU) 的本地 Python 解释器路径。
            </p>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={onValidateWan2gp}
              disabled={isValidatingWan2gp}
            >
              {isValidatingWan2gp && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              校验 Wan2GP
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
