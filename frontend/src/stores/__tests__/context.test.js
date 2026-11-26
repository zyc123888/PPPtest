import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn()
  }
}))

import { api } from '@/lib/api'
import { useAuthStore } from '../auth'
import { useContextStore } from '../context'
import { useModelConfigStore } from '../modelConfig'

describe('useContextStore', () => {
  let memoryStorage

  beforeEach(() => {
    memoryStorage = new Map()
    vi.stubGlobal('localStorage', {
      getItem: (key) => (memoryStorage.has(key) ? memoryStorage.get(key) : null),
      setItem: (key, value) => memoryStorage.set(key, String(value)),
      removeItem: (key) => memoryStorage.delete(key),
      clear: () => memoryStorage.clear()
    })
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('deduplicates concurrent project fetches and hits 30s TTL cache', async () => {
    let release
    const pending = new Promise((resolve) => {
      release = resolve
    })
    api.get.mockReturnValueOnce(pending)

    const store = useContextStore()
    const first = store.fetchProjects()
    const second = store.fetchProjects()

    expect(api.get).toHaveBeenCalledTimes(1)
    expect(api.get).toHaveBeenCalledWith('/projects')

    release([{ id: 7, name: 'Omni', workspace_id: 1 }])
    const [r1, r2] = await Promise.all([first, second])
    expect(r1).toHaveLength(1)
    expect(r2).toHaveLength(1)
    expect(store.activeProjectId).toBe(7)

    // Subsequent call within TTL reuses cache
    await store.fetchProjects()
    expect(api.get).toHaveBeenCalledTimes(1)

    // Invalidation forces fresh fetch
    store.invalidateProjects()
    api.get.mockResolvedValueOnce([{ id: 8, name: 'Updated', workspace_id: 2 }])
    const refreshed = await store.fetchProjects()
    expect(api.get).toHaveBeenCalledTimes(2)
    expect(refreshed[0].name).toBe('Updated')
  })

  it('caches environments per project and ignores stale responses after invalidation', async () => {
    let releaseStale
    const stalePromise = new Promise((resolve) => {
      releaseStale = resolve
    })
    api.get.mockReturnValueOnce(stalePromise)

    const store = useContextStore()
    const staleCall = store.fetchEnvironments(10)
    store.invalidateEnvironments(10)

    api.get.mockResolvedValueOnce([{ id: 99, name: 'Prod', project_id: 10 }])
    await store.fetchEnvironments(10)

    // Now release older in-flight promise; epoch guard keeps newer cache intact
    releaseStale([{ id: 1, name: 'Stale', project_id: 10 }])
    await staleCall

    expect(store.environmentsByProject['10']).toEqual([{ id: 99, name: 'Prod', project_id: 10 }])
  })

  it('resets context and modelConfig stores on authStore.logout()', async () => {
    const contextStore = useContextStore()
    const modelConfigStore = useModelConfigStore()
    const authStore = useAuthStore()

    api.get.mockResolvedValueOnce([{ id: 1, name: 'SecretProject', workspace_id: 3 }])
    await contextStore.fetchProjects()
    expect(memoryStorage.get('tp_active_project_id')).toBe('1')
    api.get.mockResolvedValueOnce([{ id: 2, name: 'SecretWorkspace' }])
    await contextStore.fetchWorkspaces()
    modelConfigStore.configsByWorkspace = { 3: { model: 'gpt-5.5' } }

    authStore.setToken('tok-user-a')
    api.post.mockResolvedValueOnce({})
    await authStore.logout()

    expect(contextStore.projects).toEqual([])
    expect(contextStore.workspaces).toEqual([])
    expect(contextStore.environmentsByProject).toEqual({})
    expect(contextStore.activeProjectId).toBeNull()
    expect(memoryStorage.has('tp_active_project_id')).toBe(false)
    expect(modelConfigStore.configsByWorkspace).toEqual({})
  })
})
