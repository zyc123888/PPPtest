<template>
  <el-container class="layout-root" :class="{ 'is-mobile': isMobile }">
    <div v-if="isMobile && sidebarOpened" class="mobile-overlay" @click="closeSidebar"></div>
    <el-aside class="layout-aside" :class="{ 'is-mobile': isMobile, 'is-open': sidebarOpened }" :width="asideWidth">
      <Sidebar @navigate="handleNavigate" />
    </el-aside>
    <el-container class="layout-content-col">
      <el-header class="layout-header" :height="headerHeight">
        <Header />
      </el-header>
      <el-main class="layout-main">
        <AppMain />
      </el-main>
    </el-container>
    <CommandPalette />
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAppStore } from '@/stores/app'
import Sidebar from './components/Sidebar.vue'
import Header from './components/Header.vue'
import AppMain from './components/AppMain.vue'
import CommandPalette from '@/components/CommandPalette.vue'

const appStore = useAppStore()

const headerHeight = 'var(--app-header-height)'
const asideWidth = computed(() =>
  appStore.sidebar.opened ? 'var(--app-sidebar-width)' : 'var(--app-sidebar-width-collapsed)'
)
const sidebarOpened = computed(() => appStore.sidebar.opened)
const isMobile = computed(() => appStore.sidebar.mobile)

const userAdjustedSidebar = ref(false)
let applyingSidebarDefault = false

watch(
  () => appStore.sidebar.opened,
  () => {
    if (applyingSidebarDefault) return
    userAdjustedSidebar.value = true
  },
  { flush: 'sync' }
)

const updateViewport = () => {
  const isMobileView = window.innerWidth <= 960
  appStore.setMobile(isMobileView)
  if (userAdjustedSidebar.value) return
  applyingSidebarDefault = true
  if (isMobileView) {
    appStore.closeSideBar()
  } else {
    appStore.openSideBar()
  }
  applyingSidebarDefault = false
}

const closeSidebar = () => {
  if (isMobile.value) {
    appStore.closeSideBar()
  }
}

const handleNavigate = () => {
  closeSidebar()
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
})
</script>

<style scoped>
.layout-root {
  height: 100vh;
  background: transparent;
  position: relative;
  z-index: 1;
}

.layout-aside {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border-right: 1px solid rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.layout-aside.is-mobile {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  z-index: 1201;
  transform: translateX(-100%);
  transition: transform 0.2s ease;
  box-shadow: var(--shadow-float);
}

.layout-aside.is-mobile.is-open {
  transform: translateX(0);
}

.mobile-overlay {
  position: fixed;
  inset: 0;
  background: rgba(29, 29, 31, 0.32);
  backdrop-filter: blur(4px);
  z-index: 1200;
}

.layout-content-col {
  position: relative;
  min-width: 0;
  overflow: hidden;
}

.layout-header {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  padding: 0 var(--space-24);
  display: flex;
  align-items: center;
}

.layout-main {
  padding: 0;
  background: transparent;
  overflow: auto;
}

.layout-root.is-mobile .layout-header {
  padding: 0 var(--space-12);
}
</style>
