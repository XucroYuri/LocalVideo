'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { ConfirmDialogProvider } from './common/confirm-dialog-provider'
import { NavbarProvider } from './layout/navbar-context'

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            refetchOnWindowFocus: false,
          },
        },
      })
  )

  return (
    <QueryClientProvider client={queryClient}>
      <ConfirmDialogProvider>
        <NavbarProvider>{children}</NavbarProvider>
      </ConfirmDialogProvider>
    </QueryClientProvider>
  )
}
