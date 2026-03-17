import { defineStore } from 'pinia'
import { api } from '@/lib/api'

const TOKEN_KEY = 'tp_token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null,
    loaded: false
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token)
  },
  actions: {
    setToken(token) {
      this.token = token
      if (token) {
        localStorage.setItem(TOKEN_KEY, token)
      } else {
        localStorage.removeItem(TOKEN_KEY)
      }
    },
    async fetchProfile() {
      if (!this.token) return null
      const user = await api.get('/auth/me')
      this.user = user
      this.loaded = true
      return user
    },
    async login(username, password) {
      const payload = await api.post('/auth/login', { username, password })
      this.setToken(payload.token)
      this.user = payload.user
      this.loaded = true
      return payload.user
    },
    async logout() {
      try {
        if (this.token) {
          await api.post('/auth/logout')
        }
      } catch (error) {
        // ignore logout error
      } finally {
        this.setToken('')
        this.user = null
        this.loaded = false
      }
    }
  }
})
