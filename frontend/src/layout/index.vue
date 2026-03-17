<template>
  <el-container class="layout-root" :class="{ 'is-mobile': isMobile }">
    <div v-if="isMobile && sidebarOpened" class="mobile-overlay" @click="closeSidebar"></div>
    <el-aside class="layout-aside" :class="{ 'is-mobile': isMobile, 'is-open': sidebarOpened }" :width="asideWidth">
      <Sidebar @navigate="handleNavigate" />
    </el-aside>
    <el-container>
      <el-header class="layout-header" :height="headerHeight">
        <Header />
      </el-header>
      <el-main class="layout-main">
        <AppMain />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import Sidebar from './components/Sidebar.vue'
import Header from './components/Header.vue'
import AppMain from './components/AppMain.vue'

const appStore = useAppStore()

const headerHeight = 'var(--app-header-height)'
const asideWidth = computed(() =>
  appStore.sidebar.opened ? 'var(--app-sidebar-width)' : 'var(--app-sidebar-width-collapsed)'
)
const sidebarOpened = computed(() => appStore.sidebar.opened)
const isMobile = computed(() => appStore.sidebar.mobile)

const updateViewport = () => {
  const isMobileView = window.innerWidth <= 960
  appStore.setMobile(isMobileView)
  if (isMobileView) {
    appStore.closeSideBar()
  } else {
    appStore.openSideBar()
  }
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
  background: var(--color-bg);
}

.layout-aside {
  background: #ffffff;
  border-right: 1px solid var(--el-border-color);
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
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
}

.layout-aside.is-mobile.is-open {
  transform: translateX(0);
}

.mobile-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  z-index: 1200;
}

.layout-header {
  background: #ffffff;
  border-bottom: 1px solid var(--el-border-color);
  padding: 0 var(--space-16);
  display: flex;
  align-items: center;
}

.layout-main {
  padding: 0;
  background: var(--color-bg);
  overflow: auto;
}

.layout-root.is-mobile .layout-header {
  padding: 0 var(--space-12);
}
</style>
