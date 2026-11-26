import { defineStore } from 'pinia'
import {
  getCaseGenerationModelConfig,
  listCaseGenerationModelOptions,
  saveCaseGenerationModelConfig
} from '@/lib/caseGeneration'

const DEFAULT_TTL_MS = 60_000

let optionsPromise = null
let optionsEpoch = 0
const configPromises = new Map()
const configEpochs = new Map()

export const useModelConfigStore = defineStore('modelConfig', {
  state: () => ({
    modelOptions: [],
    optionsLoadedAt: 0,
    configsByWorkspace: {},
    configLoadedAt: {}
  }),

  actions: {
    async fetchModelOptions(options = {}) {
      const { force = false, ttlMs = DEFAULT_TTL_MS } = options
      if (!force && this.optionsLoadedAt > 0 && Date.now() - this.optionsLoadedAt < ttlMs) {
        return this.modelOptions
      }
      if (!force && optionsPromise) {
        return optionsPromise
      }
      if (force) {
        optionsEpoch += 1
        optionsPromise = null
      }
      const reqEpoch = optionsEpoch
      const pending = (async () => {
        try {
          const data = (await listCaseGenerationModelOptions()) || []
          if (reqEpoch === optionsEpoch) {
            this.modelOptions = data
            this.optionsLoadedAt = Date.now()
          }
          return data
        } finally {
          if (optionsPromise === pending) {
            optionsPromise = null
          }
        }
      })()
      optionsPromise = pending
      return pending
    },

    async fetchWorkspaceConfig(workspaceId, options = {}) {
      const { force = false, ttlMs = DEFAULT_TTL_MS } = options
      if (!workspaceId) return null
      const key = String(workspaceId)
      const loadedAt = this.configLoadedAt[key] || 0
      if (!force && loadedAt > 0 && Date.now() - loadedAt < ttlMs) {
        return this.configsByWorkspace[key] || null
      }
      if (!force && configPromises.has(key)) {
        return configPromises.get(key)
      }
      const nextEpoch = (configEpochs.get(key) || 0) + (force ? 1 : 0)
      configEpochs.set(key, nextEpoch)
      if (force) {
        configPromises.delete(key)
      }
      const pending = (async () => {
        try {
          const config = await getCaseGenerationModelConfig(workspaceId)
          if ((configEpochs.get(key) || 0) === nextEpoch) {
            this.configsByWorkspace = {
              ...this.configsByWorkspace,
              [key]: config
            }
            this.configLoadedAt = {
              ...this.configLoadedAt,
              [key]: Date.now()
            }
          }
          return config
        } finally {
          if (configPromises.get(key) === pending) {
            configPromises.delete(key)
          }
        }
      })()
      configPromises.set(key, pending)
      return pending
    },

    async saveWorkspaceConfig(payload) {
      const saved = await saveCaseGenerationModelConfig(payload)
      const workspaceId = payload?.workspace_id || saved?.workspace_id
      if (workspaceId) {
        const key = String(workspaceId)
        configEpochs.set(key, (configEpochs.get(key) || 0) + 1)
        configPromises.delete(key)
        this.configsByWorkspace = {
          ...this.configsByWorkspace,
          [key]: saved
        }
        this.configLoadedAt = {
          ...this.configLoadedAt,
          [key]: Date.now()
        }
      }
      return saved
    },

    invalidateWorkspaceConfig(workspaceId) {
      if (!workspaceId) {
        configPromises.clear()
        this.configsByWorkspace = {}
        this.configLoadedAt = {}
        return
      }
      const key = String(workspaceId)
      configEpochs.set(key, (configEpochs.get(key) || 0) + 1)
      configPromises.delete(key)
      const nextLoadedAt = { ...this.configLoadedAt }
      delete nextLoadedAt[key]
      this.configLoadedAt = nextLoadedAt
    },

    reset() {
      optionsEpoch += 1
      optionsPromise = null
      configPromises.clear()
      for (const key of Object.keys(this.configsByWorkspace)) {
        configEpochs.set(key, (configEpochs.get(key) || 0) + 1)
      }
      this.modelOptions = []
      this.optionsLoadedAt = 0
      this.configsByWorkspace = {}
      this.configLoadedAt = {}
    }
  }
})
