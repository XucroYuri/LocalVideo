'use client'

import { Link2, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Settings, SettingsUpdate } from '@/types/settings'
import { RuntimeValidationBadge } from './settings-runtime-validation-badge'

interface SettingsVideoDownloaderSectionProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  onValidateXhsDownloader: () => void
  isValidatingXhsDownloader: boolean
  onValidateTiktokDownloader: () => void
  isValidatingTiktokDownloader: boolean
  onValidateKsDownloader: () => void
  isValidatingKsDownloader: boolean
}

export function SettingsVideoDownloaderSection(props: SettingsVideoDownloaderSectionProps) {
  const {
    settings,
    formData,
    updateField,
    onValidateXhsDownloader,
    isValidatingXhsDownloader,
    onValidateTiktokDownloader,
    isValidatingTiktokDownloader,
    onValidateKsDownloader,
    isValidatingKsDownloader,
  } = props
  const isContainerizedRuntime = Boolean(settings?.is_containerized_runtime)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Link2 className="h-5 w-5" />
          视频链接下载器
        </CardTitle>
        <CardDescription>下载器校验会执行 `uv sync + uv run`，无需手动填写 Python 路径</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Label htmlFor="xhs_downloader_path">XHS-Downloader 路径</Label>
            <RuntimeValidationBadge status={settings?.xhs_downloader_validation_status} />
          </div>
          <Input
            id="xhs_downloader_path"
            placeholder="/home/xxx/XHS-Downloader"
            value={formData.xhs_downloader_path ?? settings?.xhs_downloader_path ?? ''}
            onChange={(e) => updateField('xhs_downloader_path', e.target.value)}
            disabled={isContainerizedRuntime}
          />
          <p className="text-xs text-muted-foreground">
            文本库导入小红书链接时会调用该路径下的 XHS-Downloader（需包含 `main.py`）。
          </p>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={onValidateXhsDownloader}
              disabled={isValidatingXhsDownloader}
            >
              {isValidatingXhsDownloader && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              校验 XHS-Downloader
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Label htmlFor="tiktok_downloader_path">TikTokDownloader 路径</Label>
            <RuntimeValidationBadge status={settings?.tiktok_downloader_validation_status} />
          </div>
          <Input
            id="tiktok_downloader_path"
            placeholder="/home/xxx/TikTokDownloader"
            value={formData.tiktok_downloader_path ?? settings?.tiktok_downloader_path ?? ''}
            onChange={(e) => updateField('tiktok_downloader_path', e.target.value)}
            disabled={isContainerizedRuntime}
          />
          <p className="text-xs text-muted-foreground">
            文本库导入抖音链接时会调用该路径下的 TikTokDownloader（需包含 `main.py`）。
          </p>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={onValidateTiktokDownloader}
              disabled={isValidatingTiktokDownloader}
            >
              {isValidatingTiktokDownloader && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              校验 TikTokDownloader
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Label htmlFor="ks_downloader_path">KS-Downloader 路径</Label>
            <RuntimeValidationBadge status={settings?.ks_downloader_validation_status} />
          </div>
          <Input
            id="ks_downloader_path"
            placeholder="/home/xxx/KS-Downloader"
            value={formData.ks_downloader_path ?? settings?.ks_downloader_path ?? ''}
            onChange={(e) => updateField('ks_downloader_path', e.target.value)}
            disabled={isContainerizedRuntime}
          />
          <p className="text-xs text-muted-foreground">
            文本库导入快手链接时会调用该路径下的 KS-Downloader（需包含 `main.py`）。
          </p>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={onValidateKsDownloader}
              disabled={isValidatingKsDownloader}
            >
              {isValidatingKsDownloader && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              校验 KS-Downloader
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
