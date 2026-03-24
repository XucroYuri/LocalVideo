'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'
import { queryKeys } from '@/lib/query-keys'
import type { StageType, StageRunRequest } from '@/types/stage'

export function useStages(projectId: number) {
  const query = useQuery({
    queryKey: queryKeys.projectResources.stages(projectId),
    queryFn: () => api.stages.list(projectId),
    enabled: !!projectId,
  })

  return {
    data: query.data,
    stages: query.data?.items || [],
    currentStage: query.data?.current_stage,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}

export function useRunStage(projectId: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ stageType, request }: { stageType: StageType; request?: StageRunRequest }) =>
      api.stages.run(projectId, stageType, request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projectResources.stages(projectId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) })
    },
  })
}

export function useStage(projectId: number, stageType: StageType) {
  const query = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, stageType),
    queryFn: () => api.stages.get(projectId, stageType),
    enabled: !!projectId && !!stageType,
  })

  return {
    stage: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  }
}
