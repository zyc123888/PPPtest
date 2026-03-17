import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebar: {
      opened: true,
      mobile: false
    }
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
    }
  }
})
