<template>
  <div class="app-page">
    <PageHeader title="工作台" subtitle="概览系统状态、资源规模与最近执行记录">
      <template #actions>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-row :gutter="16" class="section-gap">
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="工作空间" :value="summary.workspace_count" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="项目总数" :value="summary.project_count" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="接口用例" :value="summary.api_case_count" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="UI 用例" :value="summary.ui_case_count" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="环境数量" :value="summary.environment_count" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="测试计划" :value="summary.plan_count" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="用例执行" :value="summary.run_count" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="page-card" shadow="never">
          <el-statistic title="计划报告" :value="summary.plan_run_count" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="section-gap">
      <el-col :xs="24" :lg="10">
        <el-card class="page-card" shadow="never">
          <template #header>
            <div class="toolbar">
              <div>系统健康状态</div>
              <el-tag size="small" :type="statusType(health.app_status)">{{ statusText(health.app_status) }}</el-tag>
            </div>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="数据库">
              <el-tag size="small" :type="statusType(health.database)">{{ statusText(health.database) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Redis">
              <el-tag size="small" :type="statusType(health.redis)">{{ statusText(health.redis) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="检查时间">{{ formatTime(health.checked_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="14">
        <el-card class="page-card" shadow="never">
          <template #header>
            <div class="toolbar">
              <div>执行记录</div>
              <div class="toolbar-right">
                <el-select v-model="filters.status" clearable placeholder="状态" style="width: 140px">
                  <el-option label="排队中" value="PENDING" />
                  <el-option label="执行中" value="RUNNING" />
                  <el-option label="成功" value="SUCCESS" />
                  <el-option label="失败" value="FAILED" />
                </el-select>
                <el-input v-model="filters.keyword" clearable placeholder="搜索用例名称" style="width: 220px" />
              </div>
            </div>
          </template>

          <el-table :data="pagedRuns" v-loading="loading" border class="section-gap">
            <el-table-column prop="case_type" label="类型" width="90" align="center" />
            <el-table-column prop="case_name" label="用例名称" show-overflow-tooltip />
            <el-table-column label="状态" width="110" align="center">
              <template #default="scope">
                <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="summary" label="摘要" show-overflow-tooltip />
            <el-table-column label="耗时" width="110" align="center">
              <template #default="scope">
                {{ scope.row.duration_ms ? scope.row.duration_ms + 'ms' : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="时间" width="180" align="center">
              <template #default="scope">
                {{ formatTime(scope.row.created_at) }}
              </template>
            </el-table-column>
          </el-table>

          <div class="table-pagination">
            <el-pagination
              layout="total, sizes, prev, pager, next"
              :total="filteredRuns.length"
              :page-sizes="[10, 20, 30]"
              v-model:page-size="pageSize"
              v-model:current-page="page"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'

const summary = ref({
  workspace_count: 0,
  project_count: 0,
  api_case_count: 0,
  ui_case_count: 0,
  environment_count: 0,
  plan_count: 0,
  run_count: 0,
  plan_run_count: 0,
  recent_runs: []
})

const health = ref({
  app_status: 'loading',
  database: 'loading',
  redis: 'loading',
  checked_at: ''
})

const runs = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(10)
const filters = reactive({
  keyword: '',
  status: ''
})

let timer = null

const loadAll = async () => {
  loading.value = true
  try {
    const [summaryData, healthData, runData] = await Promise.all([
      api.get('/dashboard/summary'),
      api.get('/system/health'),
      api.get('/executions/runs')
    ])
    summary.value = summaryData
    health.value = healthData
    runs.value = runData
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

const statusText = (status) => {
  const map = {
    healthy: '正常',
    degraded: '降级',
    unhealthy: '异常',
    PENDING: '排队中',
    RUNNING: '执行中',
    SUCCESS: '成功',
    FAILED: '失败',
    loading: '加载中'
  }
  return map[status] || status
}

const statusType = (status) => {
  if (['healthy', 'SUCCESS'].includes(status)) return 'success'
  if (['RUNNING', 'PENDING', 'degraded', 'loading'].includes(status)) return 'warning'
  return 'danger'
}

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const filteredRuns = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return runs.value.filter((r) => {
    if (filters.status && r.status !== filters.status) return false
    if (!keyword) return true
    return String(r.case_name || '').toLowerCase().includes(keyword)
  })
})

const pagedRuns = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRuns.value.slice(start, start + pageSize.value)
})

onMounted(() => {
  loadAll()
  timer = setInterval(loadAll, 5000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>
