<template>
  <div class="sidebar-root">
    <div class="sidebar-brand">
      <el-icon size="18"><Platform /></el-icon>
      <span v-if="!collapsed" class="brand-text" data-testid="app-title">自动化测试平台</span>
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
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { Platform } from '@element-plus/icons-vue'

const route = useRoute()
const appStore = useAppStore()
const collapsed = computed(() => !appStore.sidebar.opened)
const activePath = computed(() => route.path)

const emit = defineEmits(['navigate'])

const menuItems = computed(() => [
  { path: '/dashboard', title: '工作台', icon: 'Odometer' },
  { path: '/workspace/index', title: '工作空间', icon: 'OfficeBuilding' },
  { path: '/project/index', title: '项目管理', icon: 'Folder' },
  {
    path: '/case',
    title: '用例管理',
    icon: 'List',
    children: [
      { path: '/case/api', title: '接口用例', icon: 'Link' },
      { path: '/case/ui', title: 'UI 用例', icon: 'Monitor' }
    ]
  },
  { path: '/plan/index', title: '测试计划', icon: 'Calendar' },
  { path: '/environment/index', title: '环境管理', icon: 'Grid' },
  { path: '/execution/index', title: '执行中心', icon: 'VideoPlay' },
  { path: '/report/index', title: '报告中心', icon: 'Document' },
  { path: '/tools/index', title: '常用工具', icon: 'Tools', testId: 'tab-tools' },
  { path: '/user/index', title: '用户权限', icon: 'UserFilled' }
])

const handleSelect = () => {
  emit('navigate')
}
</script>

<style scoped>
.sidebar-root {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.sidebar-brand {
  height: var(--app-header-height);
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: 0 var(--space-16);
  border-bottom: 1px solid var(--el-border-color);
  box-sizing: border-box;
}

.brand-text {
  font-size: var(--font-18);
  font-weight: 600;
  letter-spacing: 0.2px;
}

.sidebar-scroll {
  flex: 1;
}
</style>
