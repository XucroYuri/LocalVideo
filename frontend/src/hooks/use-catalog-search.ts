'use client'

import { useCallback, useEffect, useState } from 'react'

interface UseCatalogSearchOptions {
  initialQuery?: string
  debounceMs?: number
}

export function useCatalogSearch(options: UseCatalogSearchOptions = {}) {
  const { initialQuery = '', debounceMs = 300 } = options
  const normalizedInitial = String(initialQuery).trim()
  const [searchText, setSearchText] = useState(normalizedInitial)
  const [searchQuery, setSearchQuery] = useState(normalizedInitial)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearchQuery(searchText.trim())
    }, debounceMs)
    return () => {
      window.clearTimeout(timer)
    }
  }, [debounceMs, searchText])

  const commitSearch = useCallback(() => {
    setSearchQuery(searchText.trim())
  }, [searchText])

  return {
    searchText,
    setSearchText,
    searchQuery,
    commitSearch,
  }
}
