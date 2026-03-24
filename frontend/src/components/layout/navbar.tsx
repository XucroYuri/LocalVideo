'use client'

import Link from 'next/link'
import { Settings, ArrowLeft, Edit2, Check, X, Users, Headphones, FileText } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useNavbar } from './navbar-context'

export function Navbar() {
  const { project } = useNavbar()
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const [editTitle, setEditTitle] = useState('')

  const handleStartEdit = () => {
    if (project) {
      setEditTitle(project.title)
      setIsEditingTitle(true)
    }
  }

  const handleSaveTitle = async () => {
    if (!editTitle.trim() || !project?.onTitleChange) return
    await project.onTitleChange(editTitle)
    setIsEditingTitle(false)
  }

  const handleCancelEdit = () => {
    setIsEditingTitle(false)
    setEditTitle('')
  }

  return (
    <nav className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 flex-shrink-0">
      <div className="flex h-14 items-center px-4 md:px-8 lg:px-12">
        {project ? (
          <div className="flex items-center gap-3">
            <Link href="/">
              <Button variant="ghost" size="icon">
                <ArrowLeft className="h-5 w-5" />
              </Button>
            </Link>

            {isEditingTitle ? (
              <div className="flex items-center gap-2">
                <Input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-64 h-8"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSaveTitle()
                    if (e.key === 'Escape') handleCancelEdit()
                  }}
                />
                <Button size="icon" variant="ghost" className="h-8 w-8" onClick={handleSaveTitle}>
                  <Check className="h-4 w-4" />
                </Button>
                <Button size="icon" variant="ghost" className="h-8 w-8" onClick={handleCancelEdit}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              <button
                className="flex items-center gap-2 hover:bg-accent px-2 py-1 rounded group"
                onClick={handleStartEdit}
              >
                <h1 className="text-lg font-semibold">{project.title}</h1>
                <Edit2 className="h-4 w-4 opacity-0 group-hover:opacity-50" />
              </button>
            )}
          </div>
        ) : (
          <Link href="/" className="flex items-center space-x-2">
            <span className="text-xl font-bold">LocalVideo</span>
          </Link>
        )}

        <div className="flex flex-1 items-center justify-end space-x-3">
          <Button variant="ghost" size="icon" asChild>
            <Link href={project ? `/references?from=project&projectId=${project.id}` : '/references?from=home'}>
              <Users className="h-5 w-5" />
            </Link>
          </Button>
          <Button variant="ghost" size="icon" asChild>
            <Link href="/voice-library">
              <Headphones className="h-5 w-5" />
            </Link>
          </Button>
          <Button variant="ghost" size="icon" asChild>
            <Link href="/text-library">
              <FileText className="h-5 w-5" />
            </Link>
          </Button>
          <Button variant="ghost" size="icon" asChild>
            <Link href="/settings">
              <Settings className="h-5 w-5" />
            </Link>
          </Button>
        </div>
      </div>
    </nav>
  )
}
