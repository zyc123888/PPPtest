<template>
  <div class="header-root">
    <div class="header-left">
      <el-button text @click="toggleSideBar">
        <el-icon size="18">
          <Fold v-if="sidebar.opened" />
          <Expand v-else />
        </el-icon>
      </el-button>

      <el-breadcrumb separator="/">
        <el-breadcrumb-item v-for="item in breadcrumbs" :key="item.path">
          {{ item.title }}
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <div class="header-right">
      <el-tag size="small" type="info" class="version-tag">v{{ appVersion }}</el-tag>
      <el-tag size="small" type="success">前端在线</el-tag>
      <el-dropdown trigger="click">
        <el-button text>
          <el-icon><User /></el-icon>
          {{ displayName }}
          <el-icon><CaretBottom /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>个人设置</el-dropdown-item>
            <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CaretBottom, Expand, Fold, User } from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { version as appVersion } from '../../../package.json'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const sidebar = computed(() => appStore.sidebar)

const breadcrumbs = computed(() => {
  return route.matched
    .filter((r) => r.meta && r.meta.title)
    .map((r) => ({ path: r.path, title: r.meta.title }))
})

const displayName = computed(() => {
  return authStore.user?.display_name || authStore.user?.username || '用户'
})

const toggleSideBar = () => {
  appStore.toggleSideBar()
}

const handleLogout = async () => {
  await authStore.logout()
  router.replace('/login')
}
</script>

<style scoped>
.header-root {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-16);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-16);
  overflow: hidden;
  min-width: 0;
}

.header-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-8);
  flex-shrink: 0;
}

.header-root :deep(.el-button.is-text) {
  color: var(--color-text);
}

.header-root :deep(.el-button.is-text:hover) {
  color: var(--color-primary);
  background: rgba(99, 102, 241, 0.08);
}

.header-root :deep(.el-breadcrumb__inner),
.header-root :deep(.el-breadcrumb__separator) {
  color: var(--color-text-secondary);
}

.header-root :deep(.el-tag--success) {
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.16);
  color: #047857;
}

.header-root :deep(.el-dropdown .el-button) {
  border-radius: 999px;
  padding-inline: 10px;
}

.header-root :deep(.version-tag) {
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.3px;
}
</style>
