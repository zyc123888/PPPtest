<template>
  <div class="sidebar-root" :class="{ 'is-collapsed': collapsed }">
    <div class="sidebar-brand">
      <div class="omnitest-logo">
        <BrandLogo :size="26" />
      </div>
      <div v-if="!collapsed" class="brand-meta">
        <span class="brand-text" data-testid="app-title">OmniTest</span>
        <span class="brand-tag">QA</span>
      </div>
    </div>

    <el-scrollbar class="sidebar-scroll">
      <el-menu
        router
        :collapse="collapsed"
        :default-active="activePath"
        :collapse-transition="false"
        @select="handleSelect"
      >
        <template v-for="item in menuItems" :key="item.path">
          <el-sub-menu v-if="item.children" :index="item.path">
            <template #title>
              <el-icon v-if="item.icon" class="sidebar-menu-icon"><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">
              <el-icon v-if="child.icon" class="sidebar-menu-icon"><component :is="child.icon" /></el-icon>
              <template #title>{{ child.title }}</template>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item v-else :index="item.path" :data-testid="item.testId || null">
            <el-icon v-if="item.icon" class="sidebar-menu-icon"><component :is="item.icon" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>
    </el-scrollbar>

    <div v-if="!collapsed" class="sidebar-footer">
      <button type="button" class="sidebar-cmd" @click="openCommandPalette">
        <span>快速跳转</span>
        <kbd>⌘K</kbd>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import BrandLogo from '@/components/BrandLogo.vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const collapsed = computed(() => !appStore.sidebar.opened)
const activePath = computed(() => route.path)

const emit = defineEmits(['navigate'])

function joinPaths(basePath, routePath) {
  if (!routePath) return basePath || '/'
  if (routePath.startsWith('/')) return routePath
  const base = basePath === '/' ? '' : basePath || ''
  return `${base}/${routePath}`.replace(/\/+/g, '/')
}

function normalizeMenuItems(routes, basePath, role) {
  const result = []
  for (const routeRecord of routes || []) {
    const fullPath = joinPaths(basePath, routeRecord.path)
    if (routeRecord.meta?.public) continue
    if (routeRecord.meta?.hideInMenu) continue
    if (routeRecord.path === '/:pathMatch(.*)*') continue

    const allowedRoles = routeRecord.meta?.roles || null
    if (Array.isArray(allowedRoles) && allowedRoles.length > 0 && !allowedRoles.includes(role)) {
      continue
    }

    const children = normalizeMenuItems(routeRecord.children || [], fullPath, role)
    const title = routeRecord.meta?.title
    if (title) {
      const item = {
        path: fullPath,
        title,
        icon: routeRecord.meta?.icon,
        testId: routeRecord.meta?.testId
      }
      if (children.length) {
        item.children = children
      }
      result.push(item)
      continue
    }

    if (children.length === 1) {
      result.push(children[0])
      continue
    }

    if (children.length > 1) {
      result.push(...children)
    }
  }
  return result
}

const menuItems = computed(() => {
  return normalizeMenuItems(router.options.routes, '', authStore.user?.role)
})

const handleSelect = () => {
  emit('navigate')
}

const openCommandPalette = () => {
  window.dispatchEvent(new CustomEvent('tp-open-command-palette'))
}
</script>

<style scoped>
.sidebar-root {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: transparent;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  height: var(--app-header-height);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.omnitest-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(99, 102, 241, 0.14);
  flex-shrink: 0;
}

.brand-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.brand-text {
  font-size: 15px;
  font-weight: 700;
  color: #1d1d1f;
  letter-spacing: -0.025em;
}

.brand-tag {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.sidebar-scroll {
  flex: 1;
}

.sidebar-footer {
  padding: 10px 12px;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
}

.sidebar-cmd {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.07);
  background: rgba(255, 255, 255, 0.72);
  color: #6e6e73;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.14s ease, color 0.14s ease, background 0.14s ease;
}

.sidebar-cmd:hover {
  border-color: rgba(0, 113, 227, 0.3);
  background: #ffffff;
  color: #1d1d1f;
}

.sidebar-cmd kbd {
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.07);
  background: rgba(0, 0, 0, 0.03);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: #6e6e73;
}

.sidebar-root.is-collapsed .sidebar-brand {
  justify-content: center;
  padding: 0;
}

.sidebar-root.is-collapsed :deep(.el-menu) {
  padding: 8px 0 12px;
  width: 100%;
  min-width: 0;
}

.sidebar-root.is-collapsed :deep(.el-menu-item),
.sidebar-root.is-collapsed :deep(.el-sub-menu__title) {
  width: calc(100% - 12px);
  margin: 4px auto;
  padding: 0 !important;
  box-sizing: border-box;
  justify-content: center;
}

.sidebar-root.is-collapsed :deep(.el-menu-item .el-icon),
.sidebar-root.is-collapsed :deep(.el-sub-menu__title .el-icon) {
  margin: 0;
  flex: 0 0 18px;
}

.sidebar-root :deep(.el-menu) {
  border-right: none;
  background: transparent;
  padding: 10px;
}

.sidebar-root :deep(.el-menu-item),
.sidebar-root :deep(.el-sub-menu__title) {
  border-radius: 10px;
  margin: 2px 0;
  height: 36px;
  line-height: 36px;
  font-size: 13.5px;
  font-weight: 500;
  color: #424245;
  padding-left: 11px !important;
}

.sidebar-root :deep(.el-sub-menu .el-menu-item) {
  padding-left: 34px !important;
  height: 33px;
  line-height: 33px;
  font-size: 13px;
}

.sidebar-root :deep(.el-menu-item.is-active) {
  background: rgba(0, 113, 227, 0.11);
  color: #0071e3;
  font-weight: 600;
}

.sidebar-root :deep(.el-menu-item:hover),
.sidebar-root :deep(.el-sub-menu__title:hover) {
  background: rgba(0, 0, 0, 0.045);
  color: #1d1d1f;
}

.sidebar-root :deep(.el-menu-item.is-active:hover) {
  background: rgba(0, 113, 227, 0.14);
  color: #0071e3;
}

.sidebar-root :deep(.sidebar-menu-icon) {
  color: inherit;
  width: 17px;
  height: 17px;
  flex: 0 0 17px;
  margin-right: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  opacity: 0.82;
}

.sidebar-root :deep(.el-menu-item.is-active .sidebar-menu-icon) {
  opacity: 1;
}

.sidebar-root :deep(.sidebar-menu-icon > svg) {
  display: block;
  width: 15px;
  height: 15px;
}

.sidebar-root :deep(.el-menu--collapse) {
  width: 100%;
  min-width: 0;
}

.sidebar-root :deep(.el-menu--collapse .el-menu-item),
.sidebar-root :deep(.el-menu--collapse .el-sub-menu__title) {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 !important;
  width: calc(100% - 12px);
  margin-left: auto;
  margin-right: auto;
  box-sizing: border-box;
}

.sidebar-root :deep(.el-menu--collapse .sidebar-menu-icon) {
  margin-right: 0;
  opacity: 1;
  visibility: visible;
}

.sidebar-root :deep(.el-menu--collapse .el-menu-tooltip__trigger) {
  width: 100%;
  height: 100%;
  padding: 0 !important;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}

.sidebar-root.is-collapsed :deep(.el-sub-menu__icon-arrow),
.sidebar-root :deep(.el-menu--collapse .el-sub-menu__icon-arrow) {
  display: none !important;
  opacity: 0 !important;
  width: 0 !important;
  margin: 0 !important;
  overflow: hidden !important;
}
</style>
