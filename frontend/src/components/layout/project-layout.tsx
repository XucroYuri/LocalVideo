'use client'

import { ReactNode } from 'react'

interface ProjectLayoutProps {
  children: ReactNode
}

// Navbar is already in root layout, so we just render children here
export function ProjectLayout({ children }: ProjectLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex-1">
        {children}
      </main>
    </div>
  )
}
