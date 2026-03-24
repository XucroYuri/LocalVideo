'use client'

import { createContext, useContext, useState, useCallback, ReactNode } from 'react'

interface ProjectInfo {
  id: number
  title: string
  onTitleChange?: (title: string) => Promise<void>
}

interface NavbarContextValue {
  project: ProjectInfo | null
  setProject: (project: ProjectInfo | null) => void
}

const NavbarContext = createContext<NavbarContextValue | null>(null)

export function NavbarProvider({ children }: { children: ReactNode }) {
  const [project, setProjectState] = useState<ProjectInfo | null>(null)

  const setProject = useCallback((p: ProjectInfo | null) => {
    setProjectState(p)
  }, [])

  return (
    <NavbarContext.Provider value={{ project, setProject }}>
      {children}
    </NavbarContext.Provider>
  )
}

export function useNavbar() {
  const context = useContext(NavbarContext)
  if (!context) {
    throw new Error('useNavbar must be used within NavbarProvider')
  }
  return context
}
