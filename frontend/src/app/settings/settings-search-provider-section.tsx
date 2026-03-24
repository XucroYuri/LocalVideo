import { Check, Loader2, Search } from 'lucide-react'

import { SecretInput } from '@/components/settings/secret-input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { formatCredits } from '@/lib/provider-config'
import type { Settings, SettingsUpdate, TavilyUsage } from '@/types/settings'

interface SettingsSearchProviderSectionProps {
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  settings: Settings | undefined
  showApiKeys: Record<string, boolean>
  onToggleApiKey: (key: string) => void
  formData: SettingsUpdate
  onFetchTavilyUsage: () => void
  isCheckingTavilyUsage: boolean
  tavilyUsage: TavilyUsage | null
}

export function SettingsSearchProviderSection(props: SettingsSearchProviderSectionProps) {
  const {
    updateField,
    settings,
    formData,
    showApiKeys,
    onToggleApiKey,
    onFetchTavilyUsage,
    isCheckingTavilyUsage,
    tavilyUsage,
  } = props
  const searchTavilyApiKey = formData.search_tavily_api_key ?? settings?.search_tavily_api_key ?? ''

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Search className="h-5 w-5" />
          搜索
        </CardTitle>
        <CardDescription>用于信息搜集的搜索 API</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="border rounded-lg p-4 space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <Label htmlFor="search_tavily_api_key" className="font-medium cursor-pointer">
              Tavily
            </Label>
            <Badge variant="outline">内置</Badge>
            {settings?.search_tavily_api_key_set && (
              <Badge variant="outline" className="text-green-600">
                <Check className="h-3 w-3 mr-1" />
                已配置
              </Badge>
            )}
          </div>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="search_tavily_api_key">API Key</Label>
              <SecretInput
                id="search_tavily_api_key"
                visible={Boolean(showApiKeys.tavily)}
                onToggleVisibility={() => onToggleApiKey('tavily')}
                placeholder={settings?.search_tavily_api_key_set ? '••••••••' : 'tvly-...'}
                value={searchTavilyApiKey}
                onChange={(e) => updateField('search_tavily_api_key', e.target.value)}
              />
            </div>
            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <div className="text-sm text-muted-foreground">手动查询 Tavily 额度</div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onFetchTavilyUsage}
                disabled={isCheckingTavilyUsage}
              >
                {isCheckingTavilyUsage && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                查询余量
              </Button>
            </div>
            {tavilyUsage && tavilyUsage.available && (
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="rounded-md border p-3">
                  <div className="text-muted-foreground text-xs">总体</div>
                  <div className="font-medium">{formatCredits(tavilyUsage.total_credits)}</div>
                </div>
                <div className="rounded-md border p-3">
                  <div className="text-muted-foreground text-xs">已用</div>
                  <div className="font-medium">{formatCredits(tavilyUsage.used_credits)}</div>
                </div>
                <div className="rounded-md border p-3">
                  <div className="text-muted-foreground text-xs">剩余</div>
                  <div className="font-medium">{formatCredits(tavilyUsage.remaining_credits)}</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
