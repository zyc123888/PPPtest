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
  background:
    radial-gradient(circle at 10% 0%, rgba(99, 102, 241, 0.06), transparent 26%),
    radial-gradient(circle at 100% 0%, rgba(168, 85, 247, 0.05), transparent 22%),
    linear-gradient(180deg, #eef2ff 0%, #f8fbff 32%, #eef2f7 100%);
}

.layout-aside {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 250, 255, 0.98));
  border-right: 1px solid rgba(148, 163, 184, 0.18);
  overflow: hidden;
  box-shadow: 8px 0 28px rgba(15, 23, 42, 0.04);
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
  background: rgba(15, 23, 42, 0.4);
  z-index: 1200;
}

.layout-header {
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(18px);
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
  padding: 0 var(--space-20);
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
