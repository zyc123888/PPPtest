import { defineStore } from 'pinia'

const GLASS_STORAGE_KEY = 'omnitest_glass_mode'

function readInitialGlassMode() {
  if (typeof window === 'undefined') return 'liquid'
  const saved = window.localStorage.getItem(GLASS_STORAGE_KEY)
  return saved === 'frosted' || saved === 'liquid' ? saved : 'liquid'
}

function applyGlassAttribute(mode) {
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.glass = mode
  }
}

const initialGlassMode = readInitialGlassMode()
applyGlassAttribute(initialGlassMode)

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebar: {
      opened: true,
      mobile: false
    },
    glassMode: initialGlassMode
  }),
  actions: {
    toggleSideBar() {
      this.sidebar.opened = !this.sidebar.opened
    },
    closeSideBar() {
      this.sidebar.opened = false
    },
    openSideBar() {
      this.sidebar.opened = true
    },
    setMobile(flag) {
      this.sidebar.mobile = flag
    },
    setGlassMode(mode) {
      const next = mode === 'frosted' ? 'frosted' : 'liquid'
      this.glassMode = next
      applyGlassAttribute(next)
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(GLASS_STORAGE_KEY, next)
      }
    },
    toggleGlassMode() {
      this.setGlassMode(this.glassMode === 'liquid' ? 'frosted' : 'liquid')
    }
  }
})
