'use client'

import { Check, Globe, Loader2 } from 'lucide-react'

import { SecretInput } from '@/components/settings/secret-input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { formatCredits } from '@/lib/provider-config'
import type { JinaReaderUsage, Settings, SettingsUpdate } from '@/types/settings'
import { RuntimeValidationBadge } from './settings-runtime-validation-badge'

interface SettingsWebParserSectionProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  showApiKeys: Record<string, boolean>
  onToggleApiKey: (key: string) => void
  onFetchJinaReaderUsage: () => void
  isFetchingJinaReaderUsage: boolean
  jinaReaderUsage: JinaReaderUsage | null
  onValidateCrawl4ai: () => void
  isValidatingCrawl4ai: boolean
}

export function SettingsWebParserSection(props: SettingsWebParserSectionProps) {
  const {
    settings,
    formData,
    updateField,
    showApiKeys,
    onToggleApiKey,
    onFetchJinaReaderUsage,
    isFetchingJinaReaderUsage,
    jinaReaderUsage,
    onValidateCrawl4ai,
    isValidatingCrawl4ai,
  } = props

  const jinaReaderApiKey = formData.jina_reader_api_key ?? settings?.jina_reader_api_key ?? ''
  const isJinaReaderConfigured = jinaReaderApiKey.trim().length > 0
  const jinaReaderIgnoreImages = formData.jina_reader_ignore_images ?? settings?.jina_reader_ignore_images ?? true
  const crawl4aiIgnoreImages = formData.crawl4ai_ignore_images ?? settings?.crawl4ai_ignore_images ?? true
  const crawl4aiIgnoreLinks = formData.crawl4ai_ignore_links ?? settings?.crawl4ai_ignore_links ?? true
  const crawl4aiDescription = settings?.is_containerized_runtime
    ? '镜像构建时会完成 `crawl4ai` 安装和 `crawl4ai-setup`。'
    : '非镜像启动时，请先在后端主环境执行 `uv run crawl4ai-setup`。'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="h-5 w-5" />
          网页链接解析
        </CardTitle>
        <CardDescription>用于普通网页解析</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-3 rounded-lg border p-3">
          <div className="flex items-start gap-2 flex-wrap">
            <Label className="font-medium">Jina Reader</Label>
            {isJinaReaderConfigured && (
              <Badge variant="outline" className="shrink-0 text-green-600">
                <Check className="h-3 w-3 mr-1" />
                已配置
              </Badge>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="jina_reader_api_key">API Key（可选，免费/付费均可）</Label>
            <SecretInput
              id="jina_reader_api_key"
              visible={Boolean(showApiKeys.jina_reader)}
              onToggleVisibility={() => onToggleApiKey('jina_reader')}
              placeholder="jina_xxx"
              value={jinaReaderApiKey}
              onChange={(e) => updateField('jina_reader_api_key', e.target.value)}
            />
          </div>
          <div className="space-y-2 text-xs leading-5 text-muted-foreground">
            <p>
              不带 Key 时走 IP 限流（20 RPM）；带 Key 后走 Key 限流（可提升到 500 RPM，但用完且未充值时，会受限或无法继续使用）。
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-md border px-3 py-2">
            <Checkbox
              id="jina_reader_ignore_images"
              checked={jinaReaderIgnoreImages}
              onCheckedChange={(checked) => updateField('jina_reader_ignore_images', checked === true)}
            />
            <Label htmlFor="jina_reader_ignore_images" className="cursor-pointer text-sm">
              输出忽略图片链接
            </Label>
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2">
            <div className="text-sm text-muted-foreground">
              {isJinaReaderConfigured ? '校验 Jina Reader 并查询额度' : '校验 Jina Reader 免费模式'}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onFetchJinaReaderUsage}
              disabled={isFetchingJinaReaderUsage}
            >
              {isFetchingJinaReaderUsage && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {isJinaReaderConfigured ? '校验并查询余量' : '校验 Jina Reader'}
            </Button>
          </div>
          {jinaReaderUsage && jinaReaderUsage.available && (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-md border p-3">
                <div className="text-muted-foreground text-xs">可用状态</div>
                <div className="font-medium">{jinaReaderUsage.available ? '可用' : '不可用'}</div>
              </div>
              <div className="rounded-md border p-3">
                <div className="text-muted-foreground text-xs">剩余 token</div>
                <div className="font-medium">{formatCredits(jinaReaderUsage.remaining_tokens)}</div>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-3 rounded-lg border p-3">
          <div className="flex items-center gap-2 flex-wrap">
            <Label className="font-medium">Crawl4AI</Label>
            <RuntimeValidationBadge status={settings?.crawl4ai_validation_status} />
          </div>
          <p className="text-xs leading-5 text-muted-foreground">{crawl4aiDescription}</p>
          <div className="flex items-center gap-2 rounded-md border px-3 py-2">
            <Checkbox
              id="crawl4ai_ignore_images"
              checked={crawl4aiIgnoreImages}
              onCheckedChange={(checked) => updateField('crawl4ai_ignore_images', checked === true)}
            />
            <Label htmlFor="crawl4ai_ignore_images" className="cursor-pointer text-sm">
              输出忽略图片链接
            </Label>
          </div>
          <div className="flex items-center gap-2 rounded-md border px-3 py-2">
            <Checkbox
              id="crawl4ai_ignore_links"
              checked={crawl4aiIgnoreLinks}
              onCheckedChange={(checked) => updateField('crawl4ai_ignore_links', checked === true)}
            />
            <Label htmlFor="crawl4ai_ignore_links" className="cursor-pointer text-sm">
              输出忽略网页链接（保留锚文本）
            </Label>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-foreground"
              onClick={onValidateCrawl4ai}
              disabled={isValidatingCrawl4ai}
            >
              {isValidatingCrawl4ai && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              校验 Crawl4AI
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
