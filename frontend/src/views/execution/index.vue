<template>
  <div class="app-page">
    <PageHeader title="执行中心" subtitle="查看执行记录、状态、日志与执行产物">
      <template #actions>
        <el-button :loading="listLoading" @click="getList">刷新</el-button>
      </template>
    </PageHeader>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="类型">
          <el-select v-model="filters.caseType" clearable placeholder="全部" style="width: 160px">
            <el-option label="API" value="API" />
            <el-option label="UI" value="UI" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 180px">
            <el-option label="排队中" value="PENDING" />
            <el-option label="执行中" value="RUNNING" />
            <el-option label="成功" value="SUCCESS" />
            <el-option label="失败" value="FAILED" />
            <el-option label="异常" value="ERROR" />
            <el-option label="超时" value="TIMEOUT" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="用例名称/摘要" style="width: 280px" />
        </el-form-item>
        <el-form-item label=" " class="query-actions">
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="page-card" shadow="never">
      <el-table v-loading="listLoading" :data="pagedList" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="类型" prop="case_type" width="90" align="center" />
        <el-table-column label="用例名称" prop="case_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" prop="status" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="错误类型" prop="error_type" width="120" align="center" />
        <el-table-column label="摘要" prop="summary" min-width="220" show-overflow-tooltip />
        <el-table-column label="耗时" width="110" align="center">
          <template #default="scope">
            {{ scope.row.duration_ms ? scope.row.duration_ms + 'ms' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="260">
          <template #default="scope">
            <el-button size="small" @click="handleDetail(scope.row)">详情</el-button>
            <el-button size="small" @click="openLogs(scope.row)">日志</el-button>
            <el-button size="small" @click="openArtifacts(scope.row)">产物</el-button>
            <el-button v-if="canTest" size="small" type="primary" @click="handleRerun(scope.row)">重跑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.case_name }}</div>
          <div class="mobile-card-meta">类型：{{ item.case_type }} · 状态：{{ statusText(item.status) }}</div>
          <div class="mobile-card-meta">错误：{{ item.error_type || '-' }} · 耗时：{{ item.duration_ms ? item.duration_ms + 'ms' : '-' }}</div>
          <div class="mobile-card-desc">{{ item.summary || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="handleDetail(item)">详情</el-button>
            <el-button size="small" @click="openLogs(item)">日志</el-button>
            <el-button size="small" @click="openArtifacts(item)">产物</el-button>
            <el-button v-if="canTest" size="small" type="primary" @click="handleRerun(item)">重跑</el-button>
          </div>
        </div>
      </div>

      <div class="table-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[10, 20, 30]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" title="执行详情" width="960px">
      <el-descriptions :column="3" border class="section-gap">
        <el-descriptions-item label="状态">{{ statusText(currentRun.status) }}</el-descriptions-item>
        <el-descriptions-item label="错误类型">{{ currentRun.error_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="退出码">{{ currentRun.exit_code ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ currentRun.duration_ms ? currentRun.duration_ms + 'ms' : '-' }}</el-descriptions-item>
        <el-descriptions-item label="超时阈值">{{ currentRun.timeout_seconds ? currentRun.timeout_seconds + 's' : '-' }}</el-descriptions-item>
        <el-descriptions-item label="重跑次数">{{ currentRun.retry_count || 0 }}</el-descriptions-item>
      </el-descriptions>
      <el-tabs>
        <el-tab-pane label="请求" name="req">
          <el-input :model-value="formatJson(currentRun.request_payload)" type="textarea" :rows="14" readonly />
        </el-tab-pane>
        <el-tab-pane label="响应" name="resp">
          <el-input :model-value="formatJson(currentRun.response_payload)" type="textarea" :rows="14" readonly />
        </el-tab-pane>
        <el-tab-pane label="步骤" name="steps">
          <el-input :model-value="formatJson(currentRun.step_results_json)" type="textarea" :rows="14" readonly />
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <el-dialog v-model="logDialogVisible" title="执行日志" width="960px">
      <el-tabs>
        <el-tab-pane label="标准输出">
          <el-input :model-value="logData.stdout_text || ''" type="textarea" :rows="16" readonly />
        </el-tab-pane>
        <el-tab-pane label="错误输出">
          <el-input :model-value="logData.stderr_text || ''" type="textarea" :rows="16" readonly />
        </el-tab-pane>
        <el-tab-pane label="步骤结果">
          <el-input :model-value="formatJson(logData.step_results_json)" type="textarea" :rows="16" readonly />
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <el-dialog v-model="artifactDialogVisible" title="执行产物" width="760px">
      <el-empty v-if="!artifactData.length" description="暂无产物" />
      <div v-else class="artifact-list">
        <div v-for="item in artifactData" :key="item.path" class="artifact-item">
          <div>
            <div class="artifact-name">{{ item.name }}</div>
            <div class="artifact-path">{{ item.path }}</div>
          </div>
          <el-button size="small" @click="copyArtifactPath(item.path)">复制路径</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const list = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const logDialogVisible = ref(false)
const artifactDialogVisible = ref(false)
const currentRun = ref({})
const logData = ref({})
const artifactData = ref([])
const { canTest } = usePermissions()
let timer = null

const filters = reactive({
  status: '',
  caseType: '',
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const statusText = (status) => {
  const map = {
    healthy: '正常',
    degraded: '降级',
    unhealthy: '异常',
    PENDING: '排队中',
    RUNNING: '执行中',
    SUCCESS: '成功',
    FAILED: '失败',
    ERROR: '异常',
    TIMEOUT: '超时',
    CANCELLED: '取消',
    loading: '加载中'
  }
  return map[status] || status
}

const statusType = (status) => {
  if (['healthy', 'SUCCESS'].includes(status)) return 'success'
  if (['RUNNING', 'PENDING', 'degraded', 'loading'].includes(status)) return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const formatJson = (val) => {
  if (!val) return '[]'
  try {
    return JSON.stringify(val, null, 2)
  } catch (e) {
    return String(val)
  }
}

const getList = async () => {
  try {
    const data = await api.get('/executions/runs')
    list.value = data
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((r) => {
    if (filters.status && r.status !== filters.status) return false
    if (filters.caseType && r.case_type !== filters.caseType) return false
    if (!keyword) return true
    return (
      String(r.case_name || '').toLowerCase().includes(keyword) ||
      String(r.summary || '').toLowerCase().includes(keyword)
    )
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.status = ''
  filters.caseType = ''
  filters.keyword = ''
  page.value = 1
}

const handleDetail = async (row) => {
  try {
    const data = await api.get(`/executions/runs/${row.id}`)
    currentRun.value = data
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const openLogs = async (row) => {
  try {
    logData.value = await api.get(`/executions/runs/${row.id}/logs`)
    logDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const openArtifacts = async (row) => {
  try {
    const data = await api.get(`/executions/runs/${row.id}/artifacts`)
    artifactData.value = data.artifacts || []
    artifactDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleRerun = async (row) => {
  try {
    await api.post(`/executions/runs/${row.id}/rerun`, {})
    ElMessage.success('重跑任务已提交')
    getList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const copyArtifactPath = async (path) => {
  try {
    await navigator.clipboard.writeText(path)
    ElMessage.success('路径已复制')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

onMounted(() => {
  getList()
  timer = setInterval(getList, 5000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.mobile-cards {
  display: none;
}

.artifact-list {
  display: grid;
  gap: var(--space-12);
}

.artifact-item {
  display: flex;
  justify-content: space-between;
  gap: var(--space-12);
  align-items: center;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 12px;
}

.artifact-name {
  font-weight: 600;
}

.artifact-path {
  font-size: 12px;
  color: var(--color-text-secondary);
  word-break: break-all;
}

@media (max-width: 960px) {
  .el-table {
    display: none;
  }

  .mobile-cards {
    display: grid;
    gap: var(--space-12);
  }

  .mobile-card {
    background: #ffffff;
    border: 1px solid var(--el-border-color);
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
  }

  .mobile-card-title {
    font-weight: 600;
    margin-bottom: 6px;
  }

  .mobile-card-meta {
    font-size: 12px;
    color: var(--color-text-secondary);
    margin-bottom: 4px;
  }

  .mobile-card-desc {
    font-size: 13px;
    color: var(--color-text);
    margin-bottom: 10px;
  }

  .mobile-card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-8);
  }
}
</style>
