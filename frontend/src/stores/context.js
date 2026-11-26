import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import { getSavedProjectId, saveActiveProjectId } from '@/lib/projectContext'

const DEFAULT_TTL_MS = 30_000

let workspacesPromise = null
let projectsPromise = null
const environmentPromises = new Map()

let workspacesEpoch = 0
let projectsEpoch = 0
const environmentEpochs = new Map()

export const useContextStore = defineStore('context', {
  state: () => ({
    workspaces: [],
    workspacesLoadedAt: 0,
    projects: [],
    projectsLoadedAt: 0,
    environmentsByProject: {},
    environmentsLoadedAt: {},
    activeProjectId: getSavedProjectId() || null,
    loadingWorkspaces: false,
    loadingProjects: false
  }),

  actions: {
    setActiveProjectId(projectId) {
      const normalized =
        projectId === undefined || projectId === null || projectId === '' ? null : Number(projectId)
      const valid = Number.isFinite(normalized) && normalized > 0 ? normalized : null
      this.activeProjectId = valid
      saveActiveProjectId(valid)
      return valid
    },

    resolveDefaultProjectId(projects = this.projects) {
      if (!Array.isArray(projects) || projects.length === 0) return null
      const saved = getSavedProjectId(projects)
      if (saved) {
        this.activeProjectId = saved
        return saved
      }
      if (
        this.activeProjectId &&
        projects.some((item) => Number(item.id) === Number(this.activeProjectId))
      ) {
        return Number(this.activeProjectId)
      }
      const fallback = Number(projects[0].id)
      this.setActiveProjectId(fallback)
      return fallback
    },

    async fetchWorkspaces(options = {}) {
      const { force = false, ttlMs = DEFAULT_TTL_MS } = options
      if (!force && this.workspacesLoadedAt > 0 && Date.now() - this.workspacesLoadedAt < ttlMs) {
        return this.workspaces
      }
      if (!force && workspacesPromise) {
        return workspacesPromise
      }
      if (force) {
        workspacesEpoch += 1
        workspacesPromise = null
      }
      const requestEpoch = workspacesEpoch
      this.loadingWorkspaces = true
      const pending = (async () => {
        try {
          const data = (await api.get('/workspaces')) || []
          if (requestEpoch === workspacesEpoch) {
            this.workspaces = data
            this.workspacesLoadedAt = Date.now()
          }
          return data
        } finally {
          if (workspacesPromise === pending) {
            workspacesPromise = null
          }
          if (requestEpoch === workspacesEpoch) {
            this.loadingWorkspaces = false
          }
        }
      })()
      workspacesPromise = pending
      return pending
    },

    async fetchProjects(options = {}) {
      const { force = false, ttlMs = DEFAULT_TTL_MS } = options
      if (!force && this.projectsLoadedAt > 0 && Date.now() - this.projectsLoadedAt < ttlMs) {
        return this.projects
      }
      if (!force && projectsPromise) {
        return projectsPromise
      }
      if (force) {
        projectsEpoch += 1
        projectsPromise = null
      }
      const requestEpoch = projectsEpoch
      this.loadingProjects = true
      const pending = (async () => {
        try {
          const data = (await api.get('/projects')) || []
          if (requestEpoch === projectsEpoch) {
            this.projects = data
            this.projectsLoadedAt = Date.now()
            this.resolveDefaultProjectId(data)
          }
          return data
        } finally {
          if (projectsPromise === pending) {
            projectsPromise = null
          }
          if (requestEpoch === projectsEpoch) {
            this.loadingProjects = false
          }
        }
      })()
      projectsPromise = pending
      return pending
    },

    async fetchEnvironments(projectId, options = {}) {
      const { force = false, ttlMs = DEFAULT_TTL_MS } = options
      if (!projectId) return []
      const key = String(projectId)
      const loadedAt = this.environmentsLoadedAt[key] || 0
      if (!force && loadedAt > 0 && Date.now() - loadedAt < ttlMs) {
        return this.environmentsByProject[key] || []
      }
      if (!force && environmentPromises.has(key)) {
        return environmentPromises.get(key)
      }
      const nextEpoch = (environmentEpochs.get(key) || 0) + (force ? 1 : 0)
      environmentEpochs.set(key, nextEpoch)
      if (force) {
        environmentPromises.delete(key)
      }
      const pending = (async () => {
        try {
          const data = (await api.get(`/environments?project_id=${encodeURIComponent(key)}`)) || []
          if ((environmentEpochs.get(key) || 0) === nextEpoch) {
            this.environmentsByProject = {
              ...this.environmentsByProject,
              [key]: data
            }
            this.environmentsLoadedAt = {
              ...this.environmentsLoadedAt,
              [key]: Date.now()
            }
          }
          return data
        } finally {
          if (environmentPromises.get(key) === pending) {
            environmentPromises.delete(key)
          }
        }
      })()
      environmentPromises.set(key, pending)
      return pending
    },

    invalidateWorkspaces() {
      workspacesEpoch += 1
      workspacesPromise = null
      this.workspacesLoadedAt = 0
    },

    invalidateProjects() {
      projectsEpoch += 1
      projectsPromise = null
      this.projectsLoadedAt = 0
    },

    invalidateEnvironments(projectId) {
      if (projectId === undefined || projectId === null || projectId === '') {
        for (const key of Object.keys(this.environmentsLoadedAt)) {
          environmentEpochs.set(key, (environmentEpochs.get(key) || 0) + 1)
        }
        environmentPromises.clear()
        this.environmentsLoadedAt = {}
        this.environmentsByProject = {}
        return
      }
      const key = String(projectId)
      environmentEpochs.set(key, (environmentEpochs.get(key) || 0) + 1)
      environmentPromises.delete(key)
      const nextLoadedAt = { ...this.environmentsLoadedAt }
      delete nextLoadedAt[key]
      this.environmentsLoadedAt = nextLoadedAt
    },

    reset() {
      workspacesEpoch += 1
      projectsEpoch += 1
      workspacesPromise = null
      projectsPromise = null
      for (const key of environmentPromises.keys()) {
        environmentEpochs.set(key, (environmentEpochs.get(key) || 0) + 1)
      }
      for (const key of Object.keys(this.environmentsByProject)) {
        environmentEpochs.set(key, (environmentEpochs.get(key) || 0) + 1)
      }
      environmentPromises.clear()
      this.workspaces = []
      this.workspacesLoadedAt = 0
      this.projects = []
      this.projectsLoadedAt = 0
      this.environmentsByProject = {}
      this.environmentsLoadedAt = {}
      this.activeProjectId = null
      saveActiveProjectId(null)
      this.loadingWorkspaces = false
      this.loadingProjects = false
    }
  }
})
