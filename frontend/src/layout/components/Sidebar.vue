<template>
  <div class="sidebar-root" :class="{ 'is-collapsed': collapsed }">
    <div class="sidebar-brand">
        <div class="omnitest-logo">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="10" stroke="url(#cyber-grad)" stroke-width="2.5" stroke-linecap="round" />
            <path d="M8 12L11 15L16 9" stroke="#34D399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
            <defs>
              <linearGradient id="cyber-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#6366F1" />
                <stop offset="100%" stop-color="#A855F7" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <span v-if="!collapsed" class="brand-text" data-testid="app-title">OmniTest</span>
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
              <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">
              <el-icon v-if="child.icon"><component :is="child.icon" /></el-icon>
              <template #title>{{ child.title }}</template>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item v-else :index="item.path" :data-testid="item.testId || null">
            <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>
    </el-scrollbar>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

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
</script>

<style scoped>
.sidebar-root {
  height: 100%;
  display: flex;
  flex-direction: column;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 255, 0.98)),
    radial-gradient(circle at top, rgba(99, 102, 241, 0.08), transparent 28%);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
  height: 64px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
}
.omnitest-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(168, 85, 247, 0.12));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}
.brand-text {
  font-size: 18px;
  font-weight: 700;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 40%, #a855f7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.5px;
}

.sidebar-scroll {
  flex: 1;
}

.sidebar-root.is-collapsed .sidebar-brand {
  justify-content: center;
  padding: 0;
}

.sidebar-root.is-collapsed .omnitest-logo {
  width: 34px;
  height: 34px;
  border-radius: 12px;
}

.sidebar-root.is-collapsed :deep(.el-menu) {
  padding: 8px 0 12px;
}

.sidebar-root.is-collapsed :deep(.el-menu-item),
.sidebar-root.is-collapsed :deep(.el-sub-menu__title) {
  width: calc(100% - 12px);
  margin: 6px auto;
  padding: 0 !important;
  box-sizing: border-box;
  justify-content: center;
}

.sidebar-root.is-collapsed :deep(.el-menu-item .el-icon),
.sidebar-root.is-collapsed :deep(.el-sub-menu__title .el-icon) {
  margin: 0;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  font-size: 18px;
  line-height: 1;
  opacity: 1;
  visibility: visible;
}

.sidebar-root.is-collapsed :deep(.el-menu--collapse) {
  padding-top: 6px;
}

.sidebar-root.is-collapsed :deep(.el-menu-item.is-active) {
  box-shadow: inset 0 0 0 1px rgba(79, 70, 229, 0.12);
}

.sidebar-root :deep(.el-menu) {
  border-right: none;
  background: transparent;
  padding: 8px 8px 12px;
}

.sidebar-root :deep(.el-menu-item),
.sidebar-root :deep(.el-sub-menu__title) {
  border-radius: 12px;
  margin: 4px 6px;
  height: 44px;
  line-height: 44px;
}

.sidebar-root :deep(.el-menu-item.is-active) {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.14), rgba(168, 85, 247, 0.16));
  color: #4338ca;
  font-weight: 600;
}

.sidebar-root :deep(.el-menu-item:hover),
.sidebar-root :deep(.el-sub-menu__title:hover) {
  background: rgba(99, 102, 241, 0.08);
}

.sidebar-root :deep(.el-sub-menu__title) {
  color: var(--color-text);
}

.sidebar-root :deep(.el-menu-item) {
  color: var(--color-text-secondary);
}

.sidebar-root :deep(.el-menu-item .el-icon),
.sidebar-root :deep(.el-sub-menu__title .el-icon) {
  color: inherit;
  font-size: 18px;
  line-height: 1;
}

.sidebar-root :deep(.el-menu-item .el-icon svg),
.sidebar-root :deep(.el-sub-menu__title .el-icon svg) {
  width: 18px;
  height: 18px;
}

.sidebar-root :deep(.el-menu--collapse) {
  padding-top: 8px;
}

.sidebar-root :deep(.el-menu--collapse .el-menu-item),
.sidebar-root :deep(.el-menu--collapse .el-sub-menu__title) {
  display: flex;
  justify-content: center;
  padding: 0 !important;
  width: 100%;
  box-sizing: border-box;
}

.sidebar-root :deep(.el-menu--collapse .el-menu-item .el-icon),
.sidebar-root :deep(.el-menu--collapse .el-sub-menu__title .el-icon) {
  margin-right: 0;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  font-size: 18px;
  line-height: 1;
  opacity: 1;
  visibility: visible;
}

.sidebar-root :deep(.el-menu--collapse .el-menu-item .el-icon svg),
.sidebar-root :deep(.el-menu--collapse .el-sub-menu__title .el-icon svg) {
  width: 18px;
  height: 18px;
}

.sidebar-root :deep(.el-menu--collapse .el-sub-menu__icon-arrow) {
  display: none;
}
</style>
