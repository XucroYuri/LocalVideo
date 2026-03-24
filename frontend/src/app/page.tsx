'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'

import { CatalogCreateCard } from '@/components/common/catalog-create-card'
import { CatalogListHeader } from '@/components/common/catalog-list-header'
import { CATALOG_GRID_CARD_CLASS, CATALOG_MAX_WIDTH_CLASS } from '@/components/common/catalog-layout'
import { CatalogQueryState } from '@/components/common/catalog-query-state'
import { ProjectCard } from '@/components/project/project-card'
import { CreateProjectDialog } from '@/components/project/create-project-dialog'
import { CatalogSearchActions } from '@/components/common/catalog-search-actions'
import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api-client'
import { useCatalogPagedQuery } from '@/hooks/use-catalog-paged-query'
import { queryKeys } from '@/lib/query-keys'
import { toast } from 'sonner'

export default function HomePage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()
  const [creating, setCreating] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const {
    page,
    pageSize,
    searchText,
    items: projects,
    total,
    totalPages,
    isLoading,
    isFetching,
    error,
    refetch,
    setPage,
    onSearchTextChange,
    onSearch,
    onPageSizeChange,
  } = useCatalogPagedQuery({
    getQueryKey: ({ searchQuery, page, pageSize }) => queryKeys.projects.list(searchQuery, page, pageSize),
    queryFn: ({ page, dataPageSize, searchQuery }) => api.projects.list(page, dataPageSize, searchQuery),
  })

  const handleDelete = async (id: number) => {
    const confirmed = await confirmDialog({
      title: '删除项目',
      description: '确定要删除这个项目吗？',
      confirmText: '删除',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return
    try {
      await api.projects.delete(id)
      queryClient.removeQueries({ queryKey: queryKeys.projects.detail(id), exact: true })
      queryClient.removeQueries({ queryKey: queryKeys.projectResources.sources(id), exact: true })
      queryClient.removeQueries({ queryKey: queryKeys.projectResources.stages(id), exact: true })
      queryClient.removeQueries({ queryKey: queryKeys.projectResources.stage(id), exact: false })
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.root })
      toast.success('项目已删除')
    } catch {
      toast.error('删除失败')
    }
  }

  const handleDuplicate = async (id: number) => {
    try {
      const duplicated = await api.projects.duplicate(id)
      queryClient.removeQueries({ queryKey: queryKeys.projects.detail(duplicated.id), exact: true })
      queryClient.removeQueries({ queryKey: queryKeys.projectResources.sources(duplicated.id), exact: true })
      queryClient.removeQueries({ queryKey: queryKeys.projectResources.stages(duplicated.id), exact: true })
      queryClient.removeQueries({ queryKey: queryKeys.projectResources.stage(duplicated.id), exact: false })
      setPage(1)
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.root })
      toast.success(`项目已复制为：${duplicated.title}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '复制失败')
    }
  }

  const handleRegenerateCover = async (id: number) => {
    try {
      await api.projects.regenerateCover(id)
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.root })
      queryClient.removeQueries({ queryKey: queryKeys.projects.detail(id), exact: true })
      toast.success('emoji 已更新')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'emoji 生成失败')
    }
  }

  const handleOpenCreateDialog = () => {
    if (creating) return
    setCreateDialogOpen(true)
  }

  const handleCreateProject = async (params: {
    video_mode: 'oral_script_driven' | 'audio_visual_driven'
    video_type: 'custom' | 'single_narration' | 'duo_podcast' | 'dialogue_script'
  }) => {
    if (creating) return
    setCreating(true)
    try {
      const now = new Date()
      const year = now.getFullYear()
      const month = String(now.getMonth() + 1).padStart(2, '0')
      const day = String(now.getDate()).padStart(2, '0')
      const hours = String(now.getHours()).padStart(2, '0')
      const minutes = String(now.getMinutes()).padStart(2, '0')
      const seconds = String(now.getSeconds()).padStart(2, '0')
      const timestamp = `${year}${month}${day}_${hours}${minutes}${seconds}`
      const title = `未命名项目_${timestamp}`
      const initialStyle = ''
      const project = await api.projects.create({
        title,
        style: initialStyle,
        target_duration: 60,
        video_mode: params.video_mode,
        video_type: params.video_type,
      })
      router.push(`/projects/${project.id}`)
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.root })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '创建失败')
      setCreating(false)
    }
  }

  const loadingFallback = (
    <div className={CATALOG_GRID_CARD_CLASS}>
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <Card key={i} className="overflow-hidden">
          <div className="h-24 animate-pulse bg-muted" />
          <CardContent className="p-4">
            <Skeleton className="mb-2 h-5 w-3/4" />
            <Skeleton className="h-4 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  )

  return (
    <div className="absolute inset-0 overflow-auto">
      <div className="px-4 py-8 md:px-8 lg:px-12">
        <div className={CATALOG_MAX_WIDTH_CLASS}>
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">我的项目</h1>
          </div>
          <CatalogSearchActions
            value={searchText}
            placeholder="搜索项目名称..."
            isRefreshing={isFetching}
            onValueChange={onSearchTextChange}
            onSearch={onSearch}
            onRefresh={() => {
              void refetch()
            }}
          />
        </div>

        <CatalogListHeader
          label="项目列表"
          total={total ?? 0}
          page={page}
          totalPages={totalPages}
          pageSize={pageSize}
          isFetching={isFetching}
          onPageChange={setPage}
          onPageSizeChange={onPageSizeChange}
        />

        <CatalogQueryState
          isLoading={isLoading}
          error={error}
          hasData={projects.length > 0}
          onRetry={() => {
            void refetch()
          }}
          loadingFallback={loadingFallback}
        >
          {projects.length === 0 ? (
            <div className={CATALOG_GRID_CARD_CLASS}>
              <CatalogCreateCard
                title="新建项目"
                loading={creating}
                icon={<Plus className="h-6 w-6 text-primary" />}
                className="h-[252px]"
                contentClassName="py-8"
                onClick={handleOpenCreateDialog}
              />
            </div>
          ) : (
            <div className={CATALOG_GRID_CARD_CLASS}>
              <CatalogCreateCard
                title="新建项目"
                loading={creating}
                icon={<Plus className="h-6 w-6 text-primary" />}
                className="h-[252px]"
                contentClassName="py-8"
                onClick={handleOpenCreateDialog}
              />
              {projects.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onDuplicate={handleDuplicate}
                  onDelete={handleDelete}
                  onRegenerateCover={handleRegenerateCover}
                  viewMode="grid"
                />
              ))}
            </div>
          )}
        </CatalogQueryState>
        </div>
      </div>
      <CreateProjectDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onCreateProject={handleCreateProject}
      />
    </div>
  )
}
