<template>
  <el-dialog
    v-model="visible"
    width="580px"
    :show-close="false"
    class="cmd-palette-dialog"
    align-center
    @opened="focusInput"
  >
    <div class="cmd-header">
      <el-icon class="cmd-search-icon"><Search /></el-icon>
      <input
        ref="inputRef"
        v-model="query"
        class="cmd-input"
        placeholder="输入页面名称、快捷动作或项目名...（↑↓ 选择，Enter 执行，Esc 关闭）"
        @keydown.down.prevent="moveActive(1)"
        @keydown.up.prevent="moveActive(-1)"
        @keydown.enter.prevent="executeActive"
      />
      <kbd class="cmd-kbd">ESC</kbd>
    </div>

    <div class="cmd-list" v-if="filteredCommands.length">
      <div
        v-for="(item, index) in filteredCommands"
        :key="item.id"
        class="cmd-item"
        :class="{ 'is-active': index === activeIndex }"
        @mouseenter="activeIndex = index"
        @click="runCommand(item)"
      >
        <div class="cmd-item__left">
          <el-tag size="small" effect="plain" :type="item.tagType || 'info'">{{ item.group }}</el-tag>
          <span class="cmd-item__title">{{ item.title }}</span>
        </div>
        <span class="cmd-item__hint">{{ item.hint }}</span>
      </div>
    </div>
    <div v-else class="cmd-empty">未找到匹配的页面或命令</div>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useContextStore } from '@/stores/context'

const router = useRouter()
const contextStore = useContextStore()
const visible = ref(false)
const query = ref('')
const activeIndex = ref(0)
const inputRef = ref(null)
const projects = computed(() => contextStore.projects)

const staticCommands = [
  { id: 'nav-dashboard', group: '导航', tagType: 'primary', title: '质量监控大盘', hint: '/dashboard', action: () => router.push('/dashboard') },
  { id: 'nav-workspace', group: '导航', tagType: 'primary', title: '工作空间管理', hint: '/workspace', action: () => router.push('/workspace') },
  { id: 'nav-project', group: '导航', tagType: 'primary', title: '项目与敏捷工作台', hint: '/project', action: () => router.push('/project') },
  { id: 'nav-cases', group: '导航', tagType: 'primary', title: '用例资产库', hint: '/case', action: () => router.push('/case') },
  { id: 'nav-api', group: '导航', tagType: 'primary', title: '接口测试用例', hint: '/case/api', action: () => router.push('/case/api') },
  { id: 'nav-ui', group: '导航', tagType: 'primary', title: 'UI 自动化用例（Playwright / Midscene）', hint: '/case/ui', action: () => router.push('/case/ui') },
  { id: 'nav-perf', group: '导航', tagType: 'primary', title: '性能压测用例', hint: '/case/performance', action: () => router.push('/case/performance') },
  { id: 'nav-gen2', group: '导航', tagType: 'primary', title: 'AI 智能用例生成 V2', hint: '/case/generator2', action: () => router.push('/case/generator2') },
  { id: 'nav-plan', group: '导航', tagType: 'primary', title: '测试计划编排', hint: '/plan', action: () => router.push('/plan') },
  { id: 'nav-env', group: '导航', tagType: 'primary', title: '环境与变量管理', hint: '/environment', action: () => router.push('/environment') },
  { id: 'nav-exec', group: '导航', tagType: 'primary', title: '执行中心', hint: '/execution', action: () => router.push('/execution') },
  { id: 'nav-report', group: '导航', tagType: 'primary', title: '测试报告与缺陷记录', hint: '/report', action: () => router.push('/report') },
  { id: 'nav-tools', group: '导航', tagType: 'primary', title: '测试辅助工具箱', hint: '/tools', action: () => router.push('/tools') },
  { id: 'act-new-api', group: '快捷动作', tagType: 'success', title: '新建接口测试用例', hint: '打开构建器', action: () => router.push({ path: '/case/api', query: { action: 'create' } }) },
  { id: 'act-new-ui', group: '快捷动作', tagType: 'success', title: '新建 UI 自动化用例', hint: '打开编辑器', action: () => router.push({ path: '/case/ui', query: { action: 'create' } }) },
  { id: 'act-new-perf', group: '快捷动作', tagType: 'success', title: '新建性能压测用例', hint: '打开配置弹窗', action: () => router.push({ path: '/case/performance', query: { action: 'create' } }) }
]

const allCommands = computed(() => {
  const projCommands = projects.value.map((p) => ({
    id: `proj-${p.id}`,
    group: '切换项目',
    tagType: 'warning',
    title: `切换到项目：${p.name}`,
    hint: `进入工作台 #${p.id}`,
    action: () => {
      contextStore.setActiveProjectId(p.id)
      ElMessage.success(`已切换全局项目为「${p.name}」`)
      router.push(`/projects/${p.id}/overview`)
    }
  }))
  return [...staticCommands, ...projCommands]
})

const filteredCommands = computed(() => {
  const kw = query.value.trim().toLowerCase()
  if (!kw) return allCommands.value.slice(0, 12)
  return allCommands.value.filter(
    (item) =>
      item.title.toLowerCase().includes(kw) ||
      item.group.toLowerCase().includes(kw) ||
      item.hint.toLowerCase().includes(kw)
  )
})

watch(query, () => {
  activeIndex.value = 0
})

const loadProjectsOnce = async () => {
  try {
    await contextStore.fetchProjects()
  } catch {
    // ignore if unauthenticated
  }
}

const openPalette = () => {
  visible.value = true
  query.value = ''
  activeIndex.value = 0
  loadProjectsOnce()
}

const focusInput = () => {
  inputRef.value?.focus()
}

const moveActive = (delta) => {
  const len = filteredCommands.value.length
  if (!len) return
  activeIndex.value = (activeIndex.value + delta + len) % len
}

const runCommand = (item) => {
  visible.value = false
  item.action()
}

const executeActive = () => {
  const item = filteredCommands.value[activeIndex.value]
  if (item) runCommand(item)
}

const onGlobalKeydown = (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (visible.value) {
      visible.value = false
    } else {
      openPalette()
    }
  }
}

const onCustomOpenEvent = () => openPalette()

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('tp-open-command-palette', onCustomOpenEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('tp-open-command-palette', onCustomOpenEvent)
})
</script>

<style scoped>
.cmd-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}
.cmd-search-icon {
  color: #64748b;
  font-size: 18px;
}
.cmd-input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 14px;
  color: #0f172a;
  background: transparent;
}
.cmd-kbd {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #cbd5e1;
}
.cmd-list {
  max-height: 360px;
  overflow-y: auto;
  margin-top: 8px;
}
.cmd-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s ease;
}
.cmd-item.is-active {
  background: #eef2ff;
}
.cmd-item__left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.cmd-item__title {
  font-size: 13px;
  color: #1e293b;
  font-weight: 500;
}
.cmd-item__hint {
  font-size: 12px;
  color: #94a3b8;
}
.cmd-empty {
  padding: 28px 0;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
}
</style>
