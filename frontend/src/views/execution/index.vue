<template>
  <div class="app-page">
    <PageHeader title="执行中心" subtitle="查看执行记录、状态、日志与执行产物">
      <template #actions>
        <el-button :loading="listLoading" @click="getList">刷新</el-button>
      </template>
    </PageHeader>

    <div class="execution-hero section-gap">
      <el-card class="page-card execution-hero__main" shadow="never">
        <div class="execution-hero__kicker">Run Monitor</div>
        <div class="execution-hero__title">执行流转与产物留痕统一视图</div>
        <div class="execution-hero__subtitle">
          聚合当前执行态、失败风险、超时与重跑信息，让排查入口更靠前。
        </div>
      </el-card>
      <el-card class="page-card execution-hero__stat" shadow="never">
        <el-statistic title="当前可见执行" :value="filteredList.length" />
      </el-card>
      <el-card class="page-card execution-hero__stat" shadow="never">
        <el-statistic title="运行中" :value="runningCount" />
      </el-card>
      <el-card class="page-card execution-hero__stat" shadow="never">
        <el-statistic title="失败/异常" :value="failedCount" />
      </el-card>
      <el-card class="page-card execution-hero__stat" shadow="never">
        <el-statistic title="可重跑" :value="retryableCount" />
      </el-card>
    </div>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="类型">
          <el-select v-model="filters.caseType" clearable placeholder="全部" style="width: 160px">
            <el-option label="API" value="API" />
            <el-option label="UI" value="UI" />
            <el-option label="PERF" value="PERF" />
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
            <el-option label="取消" value="CANCELLED" />
          </el-select>
        </el-form-item>
        <el-form-item label="失败原因">
          <el-select v-model="filters.errorType" clearable placeholder="全部" style="width: 180px">
            <el-option
              v-for="item in EXECUTION_ERROR_TYPE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
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
        <el-table-column label="错误类型" width="120" align="center">
          <template #default="scope">
            <el-tag v-if="scope.row.error_type" size="small" :type="errorTypeTag(scope.row.error_type)">
              {{ errorTypeText(scope.row.error_type) }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
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
            <el-button v-if="canCancel(scope.row)" size="small" type="danger" @click="handleCancel(scope.row)">取消</el-button>
            <el-button v-if="canTest" size="small" type="primary" @click="handleRerun(scope.row)">重跑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.case_name }}</div>
          <div class="mobile-card-meta">类型：{{ item.case_type }} · 状态：{{ statusText(item.status) }}</div>
          <div class="mobile-card-meta">错误：{{ errorTypeText(item.error_type) }} · 耗时：{{ item.duration_ms ? item.duration_ms + 'ms' : '-' }}</div>
          <div class="mobile-card-desc">{{ item.summary || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="handleDetail(item)">详情</el-button>
            <el-button size="small" @click="openLogs(item)">日志</el-button>
            <el-button size="small" @click="openArtifacts(item)">产物</el-button>
            <el-button v-if="canCancel(item)" size="small" type="danger" @click="handleCancel(item)">取消</el-button>
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
      <div v-if="isPrecheckFailure(currentRun)" class="precheck-callout">
        <div class="precheck-callout-title">执行前预检失败</div>
        <div class="precheck-callout-body">{{ currentRun.summary || '环境变量或模板配置校验未通过' }}</div>
      </div>
      <el-tabs>
        <el-tab-pane label="请求" name="req">
          <el-input :model-value="formatJson(currentRun.request_payload)" type="textarea" :rows="14" readonly />
        </el-tab-pane>
        <el-tab-pane label="响应" name="resp">
          <el-input :model-value="formatJson(currentRun.response_payload)" type="textarea" :rows="14" readonly />
        </el-tab-pane>
        <el-tab-pane label="步骤" name="steps">
          <el-empty v-if="!currentSteps.length" description="暂无步骤结果" />
          <el-table v-else :data="currentSteps" border class="step-table">
            <el-table-column label="#" prop="index" width="70" align="center" />
            <el-table-column label="步骤" prop="name" min-width="160" show-overflow-tooltip />
            <el-table-column label="状态" width="110" align="center">
              <template #default="scope">
                <el-tag size="small" :type="stepStatusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="110" align="center">
              <template #default="scope">
                {{ scope.row.duration_ms ? scope.row.duration_ms + 'ms' : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="详情" min-width="260">
              <template #default="scope">
                <span class="step-detail">{{ formatStepDetail(scope.row.detail) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-collapse class="raw-json-collapse">
            <el-collapse-item title="原始步骤 JSON" name="raw">
              <el-input :model-value="formatJson(currentRun.step_results_json)" type="textarea" :rows="10" readonly />
            </el-collapse-item>
          </el-collapse>
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
        <el-tab-pane v-if="isPrecheckFailure(logData)" label="预检摘要">
          <el-alert :title="logData.error_type === 'CONFIG' ? '配置预检失败' : '预检失败'" type="error" :closable="false" />
          <el-input :model-value="logData.stderr_text || logData.stdout_text || ''" type="textarea" :rows="8" readonly class="precheck-textarea" />
        </el-tab-pane>
        <el-tab-pane label="步骤结果">
          <el-empty v-if="!logSteps.length" description="暂无步骤结果" />
          <el-table v-else :data="logSteps" border class="step-table">
            <el-table-column label="#" prop="index" width="70" align="center" />
            <el-table-column label="步骤" prop="name" min-width="160" show-overflow-tooltip />
            <el-table-column label="状态" width="110" align="center">
              <template #default="scope">
                <el-tag size="small" :type="stepStatusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="详情" min-width="320">
              <template #default="scope">
                <span class="step-detail">{{ formatStepDetail(scope.row.detail) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-collapse class="raw-json-collapse">
            <el-collapse-item title="原始步骤 JSON" name="raw">
              <el-input :model-value="formatJson(logData.step_results_json)" type="textarea" :rows="10" readonly />
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <el-dialog v-model="artifactDialogVisible" title="执行产物" width="760px">
      <el-empty v-if="!artifactData.length" description="暂无产物" />
      <div v-else class="artifact-list">
        <div v-for="(item, index) in artifactData" :key="`${item.path}-${index}`" class="artifact-item">
          <div>
            <div class="artifact-name">{{ item.name }}</div>
            <div class="artifact-path">{{ item.path }}</div>
          </div>
          <div class="artifact-actions">
            <el-button size="small" type="primary" @click="downloadArtifact(index, item)">下载</el-button>
            <el-button size="small" @click="copyArtifactPath(item.path)">复制路径</el-button>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'
import {
  EXECUTION_ERROR_TYPE_OPTIONS,
  executionErrorTypeTag,
  executionErrorTypeText,
  executionStatusTag,
  executionStatusText
} from '@/lib/execution'

const list = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const logDialogVisible = ref(false)
const artifactDialogVisible = ref(false)
const currentRun = ref({})
const logData = ref({})
const artifactData = ref([])
const artifactRunId = ref(null)
const { canTest } = usePermissions()
let timer = null

const filters = reactive({
  status: '',
  caseType: '',
  errorType: '',
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const statusText = executionStatusText
const statusType = executionStatusTag

const stepStatusType = (status) => {
  if (status === 'SUCCESS') return 'success'
  if (['FAILED', 'ERROR', 'TIMEOUT'].includes(status)) return 'danger'
  if (['RUNNING', 'PENDING'].includes(status)) return 'warning'
  return 'info'
}

const isPrecheckFailure = (payload) => payload?.error_type === 'CONFIG'

const errorTypeText = executionErrorTypeText
const errorTypeTag = executionErrorTypeTag

const canCancel = (row) => {
  return canTest.value && ['PENDING', 'RUNNING'].includes(row.status)
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

const normalizeSteps = (steps) => {
  if (!Array.isArray(steps)) return []
  return steps.map((step, index) => ({
    index: index + 1,
    name: step?.name || `step_${index + 1}`,
    status: step?.status || 'UNKNOWN',
    detail: step?.detail ?? step,
    duration_ms: step?.duration_ms || null
  }))
}

const formatStepDetail = (detail) => {
  if (detail === null || detail === undefined || detail === '') return '-'
  if (typeof detail === 'string') return detail
  try {
    return JSON.stringify(detail)
  } catch (e) {
    return String(detail)
  }
}

const currentSteps = computed(() => normalizeSteps(currentRun.value.step_results_json))
const logSteps = computed(() => normalizeSteps(logData.value.step_results_json))

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
    if (filters.errorType && r.error_type !== filters.errorType) return false
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

const runningCount = computed(() => list.value.filter((item) => item.status === 'RUNNING').length)
const failedCount = computed(() => list.value.filter((item) => ['FAILED', 'ERROR', 'TIMEOUT'].includes(item.status)).length)
const retryableCount = computed(() => list.value.filter((item) => item.status !== 'SUCCESS').length)

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.status = ''
  filters.caseType = ''
  filters.errorType = ''
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
    artifactRunId.value = row.id
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

const handleCancel = async (row) => {
  try {
    await ElMessageBox.confirm(`确认取消执行 #${row.id}？`, '取消执行', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '关闭'
    })
    await api.post(`/executions/runs/${row.id}/cancel`, {})
    ElMessage.success('执行已取消')
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
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

const downloadArtifact = async (artifactIndex, artifact) => {
  if (!artifactRunId.value) return
  try {
    const token = localStorage.getItem('tp_token')
    const response = await fetch(`/api/v1/executions/runs/${artifactRunId.value}/artifacts/${artifactIndex}/download`, {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail || '下载失败')
    }
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = artifact.name || `artifact_${artifactIndex}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(objectUrl)
  } catch (error) {
    ElMessage.error(error.message || '下载失败')
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
.execution-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.execution-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.35), transparent 35%);
  color: #f8fafc;
}

.execution-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.execution-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.execution-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.execution-hero__stat {
  border-radius: 18px;
}

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

.artifact-actions {
  display: flex;
  gap: var(--space-8);
  flex-shrink: 0;
}

.step-table {
  margin-top: 12px;
}

.step-detail {
  display: inline-block;
  max-width: 100%;
  color: var(--color-text-secondary);
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.raw-json-collapse {
  margin-top: 12px;
}

.precheck-callout {
  margin: 16px 0;
  border: 1px solid rgba(220, 38, 38, 0.2);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.96), rgba(255, 251, 235, 0.92));
  border-radius: 14px;
  padding: 14px 16px;
}

.precheck-callout-title {
  color: var(--el-color-danger);
  font-weight: 700;
  margin-bottom: 6px;
}

.precheck-callout-body {
  color: var(--color-text);
  line-height: 1.6;
}

.precheck-textarea {
  margin-top: 12px;
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

  .execution-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .execution-hero__main {
    grid-column: 1 / -1;
  }
}
</style>
