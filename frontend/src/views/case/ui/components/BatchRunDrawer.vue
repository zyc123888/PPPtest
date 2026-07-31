<template>
  <el-drawer
    :model-value="modelValue"
    size="min(860px, 96vw)"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="handleClosed"
  >
    <template #header>
      <div class="batch-drawer-title">
        <el-button v-if="detail" text size="small" :icon="Back" @click="backToList">返回列表</el-button>
        <strong>{{ detail ? `批量执行 #${detail.id}` : '批量执行记录' }}</strong>
        <el-tag v-if="detail" :type="batchStatusTag(detail.status)">{{ batchStatusText(detail.status) }}</el-tag>
      </div>
    </template>

    <div v-if="!detail" v-loading="listLoading" class="batch-list">
      <el-empty v-if="!batchList.length && !listLoading" description="暂无批量执行记录" :image-size="64" />
      <el-table v-else :data="batchList" size="small" @row-click="(row) => openDetail(row.id)">
        <el-table-column label="批次" width="80"><template #default="scope">#{{ scope.row.id }}</template></el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="scope"><el-tag size="small" :type="batchStatusTag(scope.row.status)">{{ batchStatusText(scope.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="摘要" prop="summary" min-width="200" show-overflow-tooltip />
        <el-table-column label="用例" width="70" align="center" prop="total_count" />
        <el-table-column label="通过/失败" width="100" align="center">
          <template #default="scope"><span class="pass-count">{{ scope.row.pass_count }}</span> / <span class="fail-count">{{ scope.row.fail_count }}</span></template>
        </el-table-column>
        <el-table-column label="耗时" width="90"><template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template></el-table-column>
        <el-table-column label="时间" width="145"><template #default="scope">{{ formatShortTime(scope.row.created_at) }}</template></el-table-column>
      </el-table>
    </div>

    <div v-else v-loading="detailLoading" class="batch-detail">
      <div class="batch-overview">
        <div class="batch-overview__item"><span>用例总数</span><strong>{{ detail.total_count }}</strong></div>
        <div class="batch-overview__item"><span>通过</span><strong class="pass-count">{{ detail.pass_count }}</strong></div>
        <div class="batch-overview__item"><span>失败</span><strong class="fail-count">{{ detail.fail_count }}</strong></div>
        <div class="batch-overview__item"><span>成功率</span><strong>{{ successRate }}</strong></div>
        <div class="batch-overview__item"><span>耗时</span><strong>{{ formatDuration(detail.duration_ms) }}</strong></div>
      </div>
      <p class="batch-summary">{{ detail.summary || '-' }}</p>
      <div class="batch-toolbar">
        <el-button :icon="Refresh" :loading="detailLoading" @click="loadDetail">刷新</el-button>
        <el-button
          v-if="canTest"
          type="warning"
          plain
          :icon="RefreshRight"
          :disabled="!canRerun"
          :loading="rerunning"
          @click="rerunFailed"
        >失败重跑</el-button>
      </div>
      <el-table :data="detail.runs || []" size="small" @row-click="(row) => $emit('open-run', row)">
        <el-table-column label="执行" width="84"><template #default="scope">#{{ scope.row.id }}</template></el-table-column>
        <el-table-column label="用例" min-width="180" show-overflow-tooltip>
          <template #default="scope">{{ caseNameMap[scope.row.case_id] || `用例 #${scope.row.case_id}` }}</template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="scope"><el-tag size="small" :type="executionStatusTag(scope.row.status)">{{ executionStatusText(scope.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="摘要" prop="summary" min-width="180" show-overflow-tooltip />
        <el-table-column label="耗时" width="90"><template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template></el-table-column>
      </el-table>
      <p class="batch-tip">点击子执行可查看单条运行详情</p>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Back, Refresh, RefreshRight } from '@element-plus/icons-vue'
import { api } from '@/lib/api'
import { executionStatusTag, executionStatusText } from '@/lib/execution'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  batchId: { type: Number, default: null },
  projectId: { type: Number, default: null },
  caseNameMap: { type: Object, default: () => ({}) },
  canTest: { type: Boolean, default: false },
  caseType: { type: String, default: 'UI', validator: (value) => ['UI', 'API', 'PERF'].includes(value) }
})
const emit = defineEmits(['update:modelValue', 'open-run', 'finished'])

const BATCH_SEGMENT_MAP = { API: 'api', UI: 'ui', PERF: 'perf' }
const batchBase = computed(() => `/executions/${BATCH_SEGMENT_MAP[props.caseType] || 'ui'}/batch-runs`)

const batchList = ref([])
const listLoading = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const rerunning = ref(false)
let pollTimer = null

const successRate = computed(() => {
  if (!detail.value || !detail.value.total_count) return '-'
  return `${Math.round((detail.value.pass_count / detail.value.total_count) * 100)}%`
})
const canRerun = computed(() => detail.value && !['PENDING', 'RUNNING'].includes(detail.value.status) && detail.value.fail_count > 0)

const batchStatusText = (status) => ({ PENDING: '排队中', RUNNING: '执行中', SUCCESS: '全部通过', FAILED: '存在失败' }[status] || status)
const batchStatusTag = (status) => ({ PENDING: 'info', RUNNING: 'warning', SUCCESS: 'success', FAILED: 'danger' }[status] || 'info')
const formatShortTime = (value) => (value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-')
const formatDuration = (value) => (value === null || value === undefined ? '-' : value < 1000 ? `${value}ms` : `${(value / 1000).toFixed(1)}s`)

const stopPolling = () => { if (pollTimer) window.clearInterval(pollTimer); pollTimer = null }
const startPolling = () => {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    if (!props.modelValue || !detail.value) return stopPolling()
    try {
      const data = await api.get(`${batchBase.value}/${detail.value.id}`)
      detail.value = data
      if (!['PENDING', 'RUNNING'].includes(data.status)) {
        stopPolling()
        emit('finished', data)
      }
    } catch {
      stopPolling()
    }
  }, 2000)
}

const loadList = async () => {
  listLoading.value = true
  try {
    const suffix = props.projectId ? `&project_id=${props.projectId}` : ''
    batchList.value = await api.get(`${batchBase.value}?limit=20${suffix}`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const loadDetail = async () => {
  if (!detail.value) return
  detailLoading.value = true
  try {
    detail.value = await api.get(`${batchBase.value}/${detail.value.id}`)
    if (['PENDING', 'RUNNING'].includes(detail.value.status)) startPolling()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    detailLoading.value = false
  }
}

const openDetail = async (batchId) => {
  detailLoading.value = true
  try {
    detail.value = await api.get(`${batchBase.value}/${batchId}`)
    if (['PENDING', 'RUNNING'].includes(detail.value.status)) startPolling()
  } catch (error) {
    ElMessage.error(error.message)
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

const backToList = () => {
  stopPolling()
  detail.value = null
  loadList()
}

const rerunFailed = async () => {
  rerunning.value = true
  try {
    const created = await api.post(`${batchBase.value}/${detail.value.id}/rerun-failed`)
    ElMessage.success(`失败重跑批次 #${created.id} 已提交`)
    await openDetail(created.id)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    rerunning.value = false
  }
}

const handleClosed = () => {
  stopPolling()
  detail.value = null
}

watch(
  () => props.modelValue,
  async (visible) => {
    if (!visible) return
    if (props.batchId) await openDetail(props.batchId)
    else {
      detail.value = null
      await loadList()
    }
  }
)
</script>

<style scoped>
.batch-drawer-title { display: flex; align-items: center; gap: 10px; }
.batch-drawer-title strong { font-size: 16px; }
.batch-list :deep(.el-table__row) { cursor: pointer; }
.batch-detail :deep(.el-table__row) { cursor: pointer; }
.batch-overview { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border: 1px solid var(--el-border-color-lighter); border-radius: 8px; overflow: hidden; }
.batch-overview__item { padding: 12px 16px; display: flex; flex-direction: column; gap: 4px; border-right: 1px solid var(--el-border-color-lighter); }
.batch-overview__item:last-child { border-right: 0; }
.batch-overview__item span { color: var(--color-text-secondary); font-size: 12px; }
.batch-overview__item strong { font-size: 20px; }
.pass-count { color: var(--el-color-success); }
.fail-count { color: var(--el-color-danger); }
.batch-summary { margin: 12px 0; color: var(--color-text-secondary); font-size: 13px; }
.batch-toolbar { display: flex; gap: 10px; margin-bottom: 12px; }
.batch-tip { margin: 10px 0 0; color: var(--color-text-secondary); font-size: 12px; }
@media (max-width: 700px) { .batch-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
