<template>
  <div class="app-page">
    <PageHeader title="报告中心" subtitle="查看测试计划执行报告、失败明细与下载产物">
      <template #actions>
        <el-button :loading="listLoading" @click="getList">刷新</el-button>
      </template>
    </PageHeader>

    <div class="summary-grid section-gap">
      <el-card class="summary-card" shadow="never">
        <el-statistic title="报告数量" :value="list.length" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="成功计划" :value="successCount" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="失败计划" :value="failedCount" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="失败用例" :value="failedCaseCount" />
      </el-card>
    </div>

    <el-card class="page-card" shadow="never">
      <el-table v-loading="listLoading" :data="list" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="计划" prop="plan_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="项目" prop="project_name" min-width="160" show-overflow-tooltip />
        <el-table-column label="环境" prop="environment_name" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" width="120" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="总数" prop="total_count" width="90" align="center" />
        <el-table-column label="成功" prop="pass_count" width="90" align="center" />
        <el-table-column label="失败" prop="fail_count" width="90" align="center" />
        <el-table-column label="执行时间" width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="200">
          <template #default="scope">
            <el-button size="small" @click="openDetail(scope.row)">详情</el-button>
            <el-button size="small" @click="openFailures(scope.row)">失败项</el-button>
          </template>
        </el-table-column>
        <el-table-column label="下载" align="center" width="180">
          <template #default="scope">
            <el-button link type="primary" @click="downloadReport(scope.row.id, 'json')">JSON</el-button>
            <el-button link type="primary" @click="downloadReport(scope.row.id, 'junit')">JUnit</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in list" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.plan_name }}</div>
          <div class="mobile-card-meta">项目：{{ item.project_name }}</div>
          <div class="mobile-card-meta">状态：{{ statusText(item.status) }} · 成功：{{ item.pass_count }}/{{ item.total_count }}</div>
          <div class="mobile-card-desc">环境：{{ item.environment_name || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="openDetail(item)">详情</el-button>
            <el-button size="small" @click="openFailures(item)">失败项</el-button>
            <el-button size="small" @click="downloadReport(item.id, 'json')">JSON</el-button>
            <el-button size="small" @click="downloadReport(item.id, 'junit')">JUnit</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-dialog v-model="detailVisible" title="报告详情" width="960px">
      <el-descriptions :column="3" border class="section-gap">
        <el-descriptions-item label="计划">{{ report.plan_name || report.plan_run.plan_id }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusText(report.plan_run.status) }}</el-descriptions-item>
        <el-descriptions-item label="错误类型">{{ report.plan_run.error_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="总数">{{ report.plan_run.total_count }}</el-descriptions-item>
        <el-descriptions-item label="成功">{{ report.plan_run.pass_count }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ report.plan_run.fail_count }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ formatTime(report.plan_run.started_at) }}</el-descriptions-item>
        <el-descriptions-item label="结束时间">{{ formatTime(report.plan_run.finished_at) }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ report.plan_run.duration_ms ? report.plan_run.duration_ms + 'ms' : '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-table :data="report.test_runs" border>
        <el-table-column label="类型" prop="case_type" width="90" align="center" />
        <el-table-column label="用例名称" prop="case_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="摘要" prop="summary" min-width="200" show-overflow-tooltip />
        <el-table-column label="错误类型" prop="error_type" width="120" align="center" />
        <el-table-column label="耗时" width="110" align="center">
          <template #default="scope">
            {{ scope.row.duration_ms ? scope.row.duration_ms + 'ms' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center">
          <template #default="scope">
            <el-button size="small" @click="jumpToExecution(scope.row.id)">执行详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="failureVisible" title="失败明细" width="920px">
      <el-empty v-if="!failureRuns.length" description="当前报告没有失败项" />
      <el-table v-else :data="failureRuns" border>
        <el-table-column label="用例名称" prop="case_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="错误类型" prop="error_type" width="120" align="center" />
        <el-table-column label="摘要" prop="summary" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="110" align="center">
          <template #default="scope">
            <el-button size="small" @click="jumpToExecution(scope.row.id)">执行详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'

const router = useRouter()
const list = ref([])
const listLoading = ref(false)
const detailVisible = ref(false)
const failureVisible = ref(false)
const failureRuns = ref([])
const report = reactive({
  plan_name: '',
  plan_run: {},
  test_runs: []
})

const statusText = (status) => {
  const map = {
    SUCCESS: '成功',
    FAILED: '失败',
    ERROR: '异常',
    TIMEOUT: '超时',
    RUNNING: '执行中',
    PENDING: '排队中'
  }
  return map[status] || status
}

const statusType = (status) => {
  if (status === 'SUCCESS') return 'success'
  if (['RUNNING', 'PENDING'].includes(status)) return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

const successCount = computed(() => list.value.filter((item) => item.status === 'SUCCESS').length)
const failedCount = computed(() => list.value.filter((item) => item.status !== 'SUCCESS').length)
const failedCaseCount = computed(() => list.value.reduce((sum, item) => sum + (item.fail_count || 0), 0))

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const getList = async () => {
  listLoading.value = true
  try {
    list.value = await api.get('/reports')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const openDetail = async (row) => {
  try {
    const data = await api.get(`/reports/${row.id}`)
    report.plan_name = row.plan_name || ''
    report.plan_run = data.plan_run
    report.test_runs = data.test_runs
    detailVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const openFailures = async (row) => {
  try {
    const data = await api.get(`/reports/${row.id}`)
    failureRuns.value = data.test_runs.filter((item) => item.status !== 'SUCCESS')
    failureVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const jumpToExecution = (runId) => {
  detailVisible.value = false
  failureVisible.value = false
  router.push({ path: '/execution/index', query: { run_id: String(runId) } })
}

const downloadReport = async (planRunId, format) => {
  try {
    const token = localStorage.getItem('tp_token')
    const response = await fetch(`/api/v1/reports/${planRunId}/download?format=${format}`, {
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
    link.download = `plan_run_${planRunId}.${format === 'json' ? 'json' : 'xml'}`
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
})
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.summary-card {
  border-radius: 16px;
}

.mobile-cards {
  display: none;
}

@media (max-width: 960px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

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
