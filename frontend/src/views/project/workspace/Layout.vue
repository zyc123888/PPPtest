<template>
  <div class="app-page project-workspace">
    <div class="ws-header page-card">
      <div class="ws-header__left">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          <span>项目列表</span>
        </el-button>
        <el-divider direction="vertical" />
        <el-select
          v-model="currentProjectId"
          filterable
          placeholder="切换项目"
          class="ws-switcher"
          @change="handleSwitch"
        >
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-tag v-if="currentProject?.code" size="small" class="ws-code">{{ currentProject.code }}</el-tag>
        <el-tag v-if="myRole" size="small" type="success" effect="plain">{{ roleLabel }}</el-tag>
      </div>
    </div>

    <div class="ws-tabs page-card">
      <div
        v-for="tab in tabs"
        :key="tab.name"
        class="ws-tab"
        :class="{ 'is-active': route.name === tab.name }"
        @click="goTab(tab.name)"
      >
        <el-icon><component :is="tab.icon" /></el-icon>
        <span>{{ tab.label }}</span>
      </div>
    </div>

    <div class="ws-content">
      <router-view v-if="currentProject" v-slot="{ Component }">
        <component :is="Component" :project="currentProject" :my-role="myRole" @refresh-project="loadProjects" />
      </router-view>
      <el-empty v-else description="加载项目中..." />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { api } from '@/lib/api'
import { WORKSPACE_TABS, PROJECT_ROLE_LABELS } from './constants'

const route = useRoute()
const router = useRouter()

const projects = ref([])
const currentProjectId = ref(Number(route.params.id))
const myRole = ref('')

const tabs = WORKSPACE_TABS

const currentProject = computed(() => projects.value.find((p) => p.id === currentProjectId.value) || null)
const roleLabel = computed(() => PROJECT_ROLE_LABELS[myRole.value] || myRole.value)

async function loadProjects() {
  try {
    projects.value = await api.get('/projects')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function loadRole() {
  if (!currentProjectId.value) return
  try {
    const overview = await api.get(`/projects/${currentProjectId.value}/overview`)
    myRole.value = overview.my_role || ''
  } catch {
    myRole.value = ''
  }
}

function goBack() {
  router.push('/project/index')
}

function goTab(name) {
  router.push({ name, params: { id: currentProjectId.value } })
}

function handleSwitch(id) {
  router.push({ name: route.name || 'ProjectOverview', params: { id } })
}

watch(
  () => route.params.id,
  (id) => {
    currentProjectId.value = Number(id)
    loadRole()
  }
)

onMounted(async () => {
  await loadProjects()
  await loadRole()
})
</script>

<style scoped>
.ws-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.ws-header__left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ws-switcher {
  width: 220px;
}
.ws-code {
  font-family: var(--font-mono, monospace);
}
.ws-tabs {
  display: flex;
  gap: 4px;
  padding: 6px;
  margin-bottom: 12px;
  overflow-x: auto;
}
.ws-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  cursor: pointer;
  white-space: nowrap;
  color: var(--color-text-secondary, #64748b);
  transition: all 0.15s ease;
}
.ws-tab:hover {
  background: rgba(99, 102, 241, 0.08);
}
.ws-tab.is-active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.14), rgba(168, 85, 247, 0.14));
  color: #4f46e5;
  font-weight: 600;
}
.ws-content {
  min-height: 300px;
}
</style>
