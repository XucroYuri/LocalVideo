export const queryKeys = {
  projects: {
    root: ['projects'] as const,
    listBase: ['projects', 'list'] as const,
    list: (searchQuery: string, page: number, pageSize: number) =>
      ['projects', 'list', searchQuery, page, pageSize] as const,
    detail: (projectId: number) => ['project', projectId] as const,
  },
  projectResources: {
    sources: (projectId: number) => ['sources', projectId] as const,
    stages: (projectId: number) => ['stages', projectId] as const,
    stage: (projectId: number) => ['stage', projectId] as const,
    stageDetail: (projectId: number, stageType: string) => ['stage', projectId, stageType] as const,
  },
  references: {
    root: ['reference-library'] as const,
    listBase: ['reference-library', 'list'] as const,
    list: (searchQuery: string, page: number, pageSize: number) =>
      ['reference-library', 'list', searchQuery, page, pageSize] as const,
    projectImportOptions: ['reference-library', 'project-import-options'] as const,
  },
  voiceLibrary: {
    root: ['voice-library'] as const,
    listBase: ['voice-library', 'list'] as const,
    list: (searchQuery: string, page: number, pageSize: number) =>
      ['voice-library', 'list', searchQuery, page, pageSize] as const,
    active: ['voice-library-active'] as const,
  },
  textLibrary: {
    root: ['text-library'] as const,
    listBase: ['text-library', 'list'] as const,
    list: (searchQuery: string, page: number, pageSize: number) =>
      ['text-library', 'list', searchQuery, page, pageSize] as const,
    projectImportOptions: ['text-library', 'project-import-options'] as const,
  },
  settings: {
    root: ['settings'] as const,
    providers: ['settings', 'providers'] as const,
    voices: (provider: string, modelName?: string) => ['settings', 'voices', provider, modelName || ''] as const,
    wan2gpImagePresets: ['settings', 'wan2gp-image-presets'] as const,
    wan2gpVideoPresets: ['settings', 'wan2gp-video-presets'] as const,
    wan2gpAudioPresets: ['settings', 'wan2gp-audio-presets'] as const,
  },
  stageManifest: {
    root: ['stage-manifest'] as const,
  },
} as const
