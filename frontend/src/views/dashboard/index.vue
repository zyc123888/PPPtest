<template>
  <div class="app-page dashboard-console">
    <PageHeader title="工作台" subtitle="运行状态、资源规模、风险趋势集中监控">
      <template #actions>
        <div class="header-actions">
          <el-button :loading="loading" @click="loadAll">刷新</el-button>
          <el-button v-for="link in quickLinks" :key="link.path" text @click="$router.push(link.path)">
            {{ link.title }}
          </el-button>
        </div>
      </template>
    </PageHeader>

    <section class="status-strip section-gap" aria-label="系统运行状态">
      <div v-for="item in statusItems" :key="item.label" class="status-cell">
        <div class="status-cell__label">
          <span class="status-dot" :class="`status-dot--${item.tone}`" />
          {{ item.label }}
        </div>
        <strong>{{ item.value }}</strong>
        <small>{{ item.hint }}</small>
      </div>
    </section>

    <section class="monitor-grid section-gap">
      <div class="monitor-panel resource-panel">
        <div class="panel-head">
          <div>
            <h2>核心资源</h2>
            <p>资产覆盖规模</p>
          </div>
          <el-tag effect="plain" round>{{ summary.workspace_count }} 个工作空间</el-tag>
        </div>

        <div class="resource-grid">
          <div v-for="item in metricCards" :key="item.label" class="resource-cell">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </div>

      <div class="monitor-panel risk-panel">
        <div class="panel-head">
          <div>
            <h2>风险概览</h2>
            <p>失败、超时、排队状态</p>
          </div>
          <el-tag :type="criticalRunCount ? 'danger' : 'success'" effect="plain" round>
            {{ criticalRunCount ? '需要处理' : '暂无高风险' }}
          </el-tag>
        </div>

        <div class="risk-list">
          <div v-for="item in riskRows" :key="item.label" class="risk-row" :class="`risk-row--${item.tone}`">
            <div>
              <span>{{ item.label }}</span>
              <small>{{ item.hint }}</small>
            </div>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="detail-grid section-gap">
      <div class="monitor-panel trend-panel">
        <div class="panel-head">
          <div>
            <h2>最近 7 天成功率</h2>
            <p>按执行创建时间聚合</p>
          </div>
          <span class="panel-indicator">{{ trendOverview }}</span>
        </div>

        <div class="trend-body">
          <svg class="trend-chart" viewBox="0 0 640 220" preserveAspectRatio="none" aria-label="最近 7 天成功率趋势">
            <polyline class="trend-chart__axis" points="42,20 42,200 604,200" />
            <polyline class="trend-chart__grid" points="42,60 604,60" />
            <polyline class="trend-chart__grid" points="42,100 604,100" />
            <polyline class="trend-chart__grid" points="42,140 604,140" />
            <polyline class="trend-chart__grid" points="42,175 604,175" />
            <polyline class="trend-chart__line" :points="trendPolyline" />
            <circle
              v-for="point in trendPoints"
              :key="point.key"
              class="trend-chart__point"
              :cx="point.x"
              :cy="point.y"
              r="3.5"
            />
          </svg>
          <div class="trend-legend">
            <div v-for="point in trendPoints" :key="point.key" class="trend-legend__item">
              <span class="legend-date">{{ point.label }}</span>
              <strong class="legend-value">{{ point.value }}%</strong>
            </div>
          </div>
        </div>
      </div>

      <div class="monitor-panel compact-runs">
        <div class="panel-head">
          <div>
            <h2>最近异常摘要</h2>
            <p>失败、异常、超时、排队</p>
          </div>
          <el-button text @click="$router.push('/execution/index')">执行中心</el-button>
        </div>

        <div class="compact-run-list">
          <div v-for="item in priorityRuns" :key="item.id" class="compact-run">
            <div class="compact-run__main">
              <el-tag size="small" :type="statusType(item.status)" effect="plain">
                {{ statusText(item.status) }}
              </el-tag>
              <span>{{ item.case_name }}</span>
            </div>
            <small>{{ formatTime(item.created_at) }}</small>
          </div>
          <el-empty v-if="!priorityRuns.length" description="暂无异常执行" />
        </div>
      </div>
    </section>

    <section class="monitor-panel section-gap">
      <div class="panel-head recent-head">
        <div>
          <h2>最近执行记录</h2>
          <p>最新任务流</p>
        </div>
        <div class="toolbar-right">
          <el-select v-model="filters.status" clearable placeholder="状态" style="width: 140px">
            <el-option label="排队中" value="PENDING" />
            <el-option label="执行中" value="RUNNING" />
            <el-option label="成功" value="SUCCESS" />
            <el-option label="失败" value="FAILED" />
            <el-option label="异常" value="ERROR" />
            <el-option label="超时" value="TIMEOUT" />
          </el-select>
          <el-input v-model="filters.keyword" clearable placeholder="搜索用例名称" style="width: 220px" />
        </div>
      </div>

      <div class="run-list">
        <div v-for="item in pagedRuns" :key="item.id" class="run-item" :class="{ 'run-item--muted': item.status === 'SUCCESS' }">
          <div class="run-item__head">
            <div class="run-item__title">
              <el-tag size="small" :type="statusType(item.status)" effect="plain">{{ statusText(item.status) }}</el-tag>
              <span>{{ item.case_name }}</span>
            </div>
            <div class="run-item__meta">{{ formatTime(item.created_at) }}</div>
          </div>
          <div class="run-item__body">
            <span>类型：{{ item.case_type }}</span>
            <span>耗时：{{ item.duration_ms ? item.duration_ms + 'ms' : '-' }}</span>
            <span class="run-item__summary">{{ item.summary || '暂无摘要' }}</span>
          </div>
        </div>
        <el-empty v-if="!pagedRuns.length" description="暂无最近执行记录" />
      </div>

      <div class="table-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredRuns.length"
          :page-sizes="[8, 16, 24]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </section>
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
const pageSize = ref(8)
const filters = reactive({
  keyword: '',
  status: ''
})

const quickLinks = [
  { title: '接口用例', desc: '进入请求构建器', path: '/case/api' },
  { title: '测试计划', desc: '编排计划和风险用例', path: '/plan/index' },
  { title: '执行中心', desc: '看日志、产物和状态', path: '/execution/index' },
  { title: '报告中心', desc: '看趋势和失败聚合', path: '/report/index' }
]

const metricCards = computed(() => ([
  { label: '工作空间', value: summary.value.workspace_count },
  { label: '项目总数', value: summary.value.project_count },
  { label: '接口用例', value: summary.value.api_case_count },
  { label: 'UI 用例', value: summary.value.ui_case_count },
  { label: '环境数量', value: summary.value.environment_count },
  { label: '测试计划', value: summary.value.plan_count },
  { label: '用例执行', value: summary.value.run_count },
  { label: '计划报告', value: summary.value.plan_run_count }
]))

const successRate = computed(() => {
  if (!runs.value.length) return 0
  const successTotal = runs.value.filter((run) => run.status === 'SUCCESS').length
  return Math.round((successTotal / runs.value.length) * 100)
})

const runningCount = computed(() => runs.value.filter((run) => run.status === 'RUNNING').length)
const pendingCount = computed(() => runs.value.filter((run) => run.status === 'PENDING').length)
const successCount = computed(() => runs.value.filter((run) => run.status === 'SUCCESS').length)
const failedCount = computed(() => runs.value.filter((run) => ['FAILED', 'ERROR'].includes(run.status)).length)
const timeoutCount = computed(() => runs.value.filter((run) => run.status === 'TIMEOUT').length)
const criticalRunCount = computed(() => runs.value.filter((run) => ['FAILED', 'ERROR', 'TIMEOUT'].includes(run.status)).length)
const stalledRunCount = computed(() => runs.value.filter((run) => ['PENDING', 'RUNNING'].includes(run.status)).length)

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
    loading: '加载中'
  }
  return map[status] || status
}

const statusTone = (status) => {
  if (['healthy', 'SUCCESS'].includes(status)) return 'success'
  if (['RUNNING', 'PENDING', 'degraded', 'loading'].includes(status)) return 'warning'
  return 'danger'
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

const statusItems = computed(() => ([
  {
    label: '应用',
    value: statusText(health.value.app_status),
    hint: 'FastAPI 服务',
    tone: statusTone(health.value.app_status)
  },
  {
    label: '数据库',
    value: statusText(health.value.database),
    hint: '主数据连接',
    tone: statusTone(health.value.database)
  },
  {
    label: 'Redis',
    value: statusText(health.value.redis),
    hint: '队列与缓存',
    tone: statusTone(health.value.redis)
  },
  {
    label: '最近刷新',
    value: formatTime(health.value.checked_at),
    hint: loading.value ? '正在同步' : '5 秒自动刷新',
    tone: loading.value ? 'warning' : 'neutral'
  }
]))

const riskRows = computed(() => ([
  { label: '失败 / 异常', value: failedCount.value, hint: 'FAILED + ERROR', tone: failedCount.value ? 'danger' : 'neutral' },
  { label: '超时', value: timeoutCount.value, hint: 'TIMEOUT', tone: timeoutCount.value ? 'warning' : 'neutral' },
  { label: '排队 / 执行中', value: stalledRunCount.value, hint: `${pendingCount.value} 排队，${runningCount.value} 执行中`, tone: stalledRunCount.value ? 'info' : 'neutral' },
  { label: '近 50 次成功率', value: `${successRate.value}%`, hint: successTrendText.value, tone: successRate.value >= 80 ? 'success' : 'warning' }
]))

const priorityRuns = computed(() => {
  const risky = runs.value.filter((run) => ['FAILED', 'ERROR', 'TIMEOUT', 'PENDING', 'RUNNING'].includes(run.status))
  return risky.slice(0, 6)
})

const buildTrendDays = () => {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(now)
    date.setDate(now.getDate() - (6 - index))
    const key = date.toISOString().slice(0, 10)
    return { key, label: `${date.getMonth() + 1}/${date.getDate()}`, total: 0, success: 0 }
  })
}

const toDateKey = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

const trendData = computed(() => {
  const buckets = buildTrendDays()
  const bucketMap = new Map(buckets.map((item) => [item.key, item]))
  runs.value.forEach((run) => {
    const bucket = bucketMap.get(toDateKey(run.created_at))
    if (!bucket) return
    bucket.total += 1
    if (run.status === 'SUCCESS') bucket.success += 1
  })
  return buckets.map((bucket) => ({
    ...bucket,
    value: bucket.total ? Math.round((bucket.success / bucket.total) * 100) : 0
  }))
})

const trendPoints = computed(() => {
  const left = 42
  const right = 604
  const top = 24
  const bottom = 200
  const width = right - left
  const height = bottom - top

  return trendData.value.map((item, index) => {
    const x = left + (trendData.value.length === 1 ? 0 : (width * index) / (trendData.value.length - 1))
    const ratio = Math.max(0, Math.min(100, item.value)) / 100
    const y = bottom - ratio * height
    return { ...item, x, y }
  })
})

const trendPolyline = computed(() => trendPoints.value.map((point) => `${point.x},${point.y}`).join(' '))

const trendOverview = computed(() => {
  const latest = trendData.value.at(-1)?.value || 0
  const previous = trendData.value.at(-2)?.value || 0
  const delta = latest - previous
  const sign = delta > 0 ? '+' : ''
  return `最近一天 ${latest}% (${sign}${delta}%)`
})

const successTrendText = computed(() => {
  const latest = trendData.value.at(-1)?.value || 0
  const previous = trendData.value.at(-2)?.value || 0
  const delta = latest - previous
  if (delta === 0) return '与前一日持平'
  return delta > 0 ? `较前一日 +${delta}%` : `较前一日 ${delta}%`
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

<style scoped>
.dashboard-console {
  color: #111827;
}

:deep(.page-header-actions .el-button--primary) {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #115e59;
  --el-button-hover-border-color: #115e59;
  --el-button-active-bg-color: #134e4a;
  --el-button-active-border-color: #134e4a;
  --el-button-text-color: #ffffff;
  border-radius: 8px;
  font-weight: 600;
}

:deep(.page-header-actions .el-button:not(.el-button--primary)) {
  border-color: #d7dee8;
  color: #334155;
  border-radius: 8px;
  font-weight: 500;
}

:deep(.page-header-actions .el-button:not(.el-button--primary):hover) {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

:deep(.page-header-actions .el-button.is-text) {
  color: #475569;
  font-weight: 500;
}

:deep(.page-header-actions .el-button.is-text:hover) {
  background: #eef2f7;
  color: #0f172a;
}

.status-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 10px;
  border: 1px solid #dbe3ee;
  border-radius: 8px;
  background: #f8fafc;
}

.status-cell {
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
}

.status-cell:hover {
  border-color: #cbd5e1;
}

.status-cell__label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.status-cell strong {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  color: #111827;
  font-size: 16px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-cell small {
  display: block;
  margin-top: 3px;
  color: #94a3b8;
  font-size: 11px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #94a3b8;
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.14);
}

.status-dot--success {
  background: #16a34a;
  box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.12);
}

.status-dot--warning {
  background: #d97706;
  box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.12);
}

.status-dot--danger {
  background: #dc2626;
  box-shadow: 0 0 0 3px rgba(220, 38, 38, 0.12);
}

.status-dot--neutral {
  background: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.monitor-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.9fr);
  gap: 14px;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.8fr);
  gap: 14px;
}

.monitor-panel {
  border: 1px solid #dbe3ee;
  border-radius: 8px;
  background: #ffffff;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.monitor-panel:hover {
  border-color: #cbd5e1;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-head h2 {
  margin: 0;
  color: #111827;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.35;
}

.panel-head p {
  margin: 3px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.panel-indicator {
  flex-shrink: 0;
  padding: 4px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  color: #334155;
  background: #f8fafc;
  font-size: 12px;
  font-weight: 500;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  overflow: hidden;
}

.resource-cell {
  min-height: 74px;
  padding: 12px;
  border-right: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
}

.resource-cell:hover {
  background: #f8fafc;
}

.resource-cell:nth-child(4n) {
  border-right: 0;
}

.resource-cell:nth-last-child(-n + 4) {
  border-bottom: 0;
}

.resource-cell span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.resource-cell strong {
  display: block;
  margin-top: 8px;
  color: #111827;
  font-size: 24px;
  line-height: 1;
  letter-spacing: 0;
}

.risk-list {
  display: grid;
  gap: 8px;
}

.risk-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-left-width: 3px;
  border-radius: 7px;
  background: #ffffff;
}

.risk-row:hover {
  background: #f8fafc;
}

.risk-row span {
  display: block;
  color: #334155;
  font-size: 13px;
  font-weight: 650;
}

.risk-row small {
  display: block;
  margin-top: 3px;
  color: #94a3b8;
  font-size: 11px;
}

.risk-row strong {
  color: #111827;
  font-size: 22px;
  line-height: 1;
}

.risk-row--danger {
  border-left-color: #dc2626;
}

.risk-row--warning {
  border-left-color: #d97706;
}

.risk-row--success {
  border-left-color: #16a34a;
}

.risk-row--info {
  border-left-color: #2563eb;
}

.risk-row--neutral {
  border-left-color: #cbd5e1;
}

.trend-body {
  display: grid;
  gap: 10px;
}

.trend-chart {
  width: 100%;
  height: 240px;
  border: 1px solid rgba(129, 140, 248, 0.12);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 255, 0.98));
  display: block;
}

.trend-chart__axis {
  fill: none;
  stroke: #94a3b8;
  stroke-width: 1;
}

.trend-chart__grid {
  fill: none;
  stroke: #e2e8f0;
  stroke-dasharray: 3 6;
  stroke-width: 1;
}

.trend-chart__line {
  fill: none;
  stroke: #0f766e;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.5;
}

.trend-chart__point {
  fill: #0f766e;
  stroke: #ffffff;
  stroke-width: 1.5;
}

.trend-legend {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}

.trend-legend__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 9px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #f8fafc;
  font-size: 12px;
}

.legend-date {
  color: #64748b;
}

.legend-value {
  color: #111827;
  font-weight: 600;
}

.compact-run-list {
  display: grid;
  gap: 8px;
}

.compact-run {
  display: grid;
  gap: 5px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
}

.compact-run:hover {
  background: #f8fafc;
}

.compact-run__main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.compact-run__main span:last-child {
  overflow: hidden;
  color: #334155;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compact-run small {
  color: #94a3b8;
  font-size: 11px;
}

.recent-head {
  align-items: center;
}

.toolbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-right :deep(.el-select .el-input__wrapper) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #d7dee8 inset;
}

.toolbar-right :deep(.el-input .el-input__wrapper) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #d7dee8 inset;
}

.run-list {
  display: grid;
  gap: 8px;
}

.run-item {
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #94a3b8;
  border-radius: 7px;
  background: #ffffff;
}

.run-item:hover {
  background: #f8fafc;
}

.run-item--muted {
  border-left-color: #cbd5e1;
  background: #fbfdff;
}

.run-item__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.run-item__title {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  color: #334155;
  font-weight: 650;
}

.run-item__title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-item__meta {
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 12px;
}

.run-item__body {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 7px;
  color: #64748b;
  font-size: 12px;
}

.run-item__summary {
  flex: 1;
  min-width: 180px;
  color: #334155;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 10px;
}

.table-pagination :deep(.el-pagination) {
  padding: 10px 14px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.table-pagination :deep(.el-pager li) {
  border-radius: 6px;
  font-weight: 500;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
}

.table-pagination :deep(.el-pager li.is-active) {
  background: #0f766e;
  color: #fff;
}

.table-pagination :deep(.el-pager li:not(.is-active):hover) {
  background: #e2e8f0;
  color: #111827;
}

.table-pagination :deep(.btn-prev),
.table-pagination :deep(.btn-next) {
  border-radius: 6px;
  background: #ffffff;
  border: 1px solid #d7dee8;
}

.table-pagination :deep(.btn-prev:hover),
.table-pagination :deep(.btn-next:hover) {
  background: #eef2f7;
  border-color: #94a3b8;
}

@media (max-width: 1100px) {
  .monitor-grid,
  .detail-grid,
  .status-strip {
    grid-template-columns: 1fr;
  }

  .resource-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .resource-cell:nth-child(4n) {
    border-right: 1px solid #e2e8f0;
  }

  .resource-cell:nth-child(2n) {
    border-right: 0;
  }

  .resource-cell:nth-last-child(-n + 4) {
    border-bottom: 1px solid #e2e8f0;
  }

  .resource-cell:nth-last-child(-n + 2) {
    border-bottom: 0;
  }
}

@media (max-width: 720px) {
  .panel-head,
  .recent-head,
  .run-item__head {
    align-items: flex-start;
    flex-direction: column;
  }

  .header-actions,
  .toolbar-right {
    justify-content: flex-start;
  }

  .resource-grid,
  .trend-legend {
    grid-template-columns: 1fr;
  }

  .resource-cell,
  .resource-cell:nth-child(2n),
  .resource-cell:nth-child(4n) {
    border-right: 0;
  }

  .resource-cell:nth-last-child(-n + 2) {
    border-bottom: 1px solid #e2e8f0;
  }

  .resource-cell:last-child {
    border-bottom: 0;
  }

  .run-item__body {
    flex-direction: column;
    gap: 6px;
  }
}
</style>
