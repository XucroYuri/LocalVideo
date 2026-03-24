'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery, type QueryKey } from '@tanstack/react-query'

import { resolveDataPageSize, resolveTotalPages } from '@/components/common/catalog-pagination'
import { useCatalogSearch } from '@/hooks/use-catalog-search'

export interface CatalogPagedQueryParams {
  page: number
  pageSize: number
  dataPageSize: number
  searchQuery: string
}

export interface CatalogPagedQueryResponse<TItem> {
  items: TItem[]
  total: number
}

interface UseCatalogPagedQueryOptions<TItem> {
  getQueryKey: (params: { searchQuery: string; page: number; pageSize: number }) => QueryKey
  queryFn: (params: CatalogPagedQueryParams) => Promise<CatalogPagedQueryResponse<TItem>>
  includeCreateCard?: boolean
  initialPageSize?: number
  initialQuery?: string
  debounceMs?: number
}

export function useCatalogPagedQuery<TItem>(options: UseCatalogPagedQueryOptions<TItem>) {
  const {
    getQueryKey,
    queryFn,
    includeCreateCard = true,
    initialPageSize = 20,
    initialQuery = '',
    debounceMs = 300,
  } = options

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(initialPageSize)
  const { searchText, setSearchText, searchQuery, commitSearch } = useCatalogSearch({
    initialQuery,
    debounceMs,
  })

  const dataPageSize = useMemo(
    () => resolveDataPageSize(pageSize, includeCreateCard),
    [includeCreateCard, pageSize]
  )

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: getQueryKey({ searchQuery, page, pageSize }),
    queryFn: () =>
      queryFn({
        page,
        pageSize,
        dataPageSize,
        searchQuery,
      }),
    placeholderData: (previous) => previous,
  })

  const items = useMemo(() => data?.items ?? [], [data?.items])
  const total = data?.total
  const totalPages = useMemo(
    () => resolveTotalPages(total ?? 0, pageSize, includeCreateCard),
    [includeCreateCard, pageSize, total]
  )

  useEffect(() => {
    if (typeof total !== 'number') return
    if (page > totalPages) {
      const timer = setTimeout(() => setPage(totalPages), 0)
      return () => clearTimeout(timer)
    }
  }, [page, total, totalPages])

  const onSearchTextChange = useCallback(
    (value: string) => {
      setPage(1)
      setSearchText(value)
    },
    [setSearchText]
  )

  const onSearch = useCallback(() => {
    setPage(1)
    commitSearch()
  }, [commitSearch])

  const onPageSizeChange = useCallback((nextPageSize: number) => {
    setPageSize(nextPageSize)
    setPage(1)
  }, [])

  return {
    page,
    pageSize,
    searchText,
    searchQuery,
    items,
    total,
    totalPages,
    isLoading,
    isFetching,
    error,
    refetch,
    setPage,
    setPageSize,
    setSearchText,
    onSearchTextChange,
    onSearch,
    onPageSizeChange,
  }
}
