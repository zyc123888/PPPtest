<template>
  <div class="bento-stage">
    <div class="bento-container">
      <header class="bn-header">
        <div>
          <h1 class="bn-title">工作台</h1>
          <p class="bn-subtitle">服务健康、测试资产规模与近期执行趋势总览</p>
        </div>
        <div class="bn-header__actions">
          <div class="bn-switch-pill">
            <span>自动刷新</span>
            <el-switch v-model="autoRefresh" size="small" />
          </div>
          <button type="button" class="bn-btn" :disabled="loading" @click="loadAll(false)">刷新</button>
          <button type="button" class="bn-btn bn-btn--primary" @click="$router.push('/execution/index')">
            进入执行中心
          </button>
        </div>
      </header>

      <!-- Quick Shortcut Bento Bar -->
      <section class="bn-shortcuts">
        <button
          v-for="link in quickLinks"
          :key="link.path"
          type="button"
          class="bn-shortcut"
          @click="$router.push(link.path)"
        >
          <span class="bn-shortcut__title">{{ link.title }}</span>
          <span class="bn-shortcut__desc">{{ link.desc }}</span>
        </button>
      </section>

      <!-- Top Bento Grid: Health + Pass Rate Ring + Risk Summary -->
      <section class="bn-top-grid">
        <div class="bn-card bn-health-card" aria-label="系统运行状态">
          <div class="bn-card__head">
            <h2>系统服务状态</h2>
            <span class="bn-pill" :class="health.app_status === 'healthy' ? 'bn-pill--green' : 'bn-pill--amber'">
              {{ statusText(health.app_status) }}
            </span>
          </div>
          <div class="bn-health-grid">
            <div v-for="item in statusItems" :key="item.label" class="bn-health-item">
              <div class="bn-health-item__top">
                <span class="bn-dot" :class="`bn-dot--${item.tone}`" />
                <span>{{ item.label }}</span>
              </div>
              <strong>{{ item.value }}</strong>
              <small>{{ item.hint }}</small>
            </div>
          </div>
        </div>

        <div class="bn-card bn-score-card">
          <div class="bn-card__head">
            <h2>近 50 次通过率</h2>
            <span class="bn-muted">{{ successTrendText }}</span>
          </div>
          <div class="bn-score-body">
            <div class="bn-score-num">{{ successRate }}<span>%</span></div>
            <div class="bn-score-bars">
              <div class="bn-mini-row">
                <span>失败 / 异常</span>
                <strong :class="{ 'is-red': failedCount > 0 }">{{ failedCount }}</strong>
              </div>
              <div class="bn-mini-row">
                <span>超时</span>
                <strong :class="{ 'is-amber': timeoutCount > 0 }">{{ timeoutCount }}</strong>
              </div>
              <div class="bn-mini-row">
                <span>排队 / 执行中</span>
                <strong :class="{ 'is-blue': stalledRunCount > 0 }">{{ stalledRunCount }}</strong>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Asset Bento Tiles -->
      <section class="bn-card bn-assets-card">
        <div class="bn-card__head">
          <h2>测试资产全景</h2>
          <span class="bn-muted">{{ summary.workspace_count }} 个工作空间 · {{ summary.project_count }} 个项目</span>
        </div>
        <div class="bn-assets-grid">
          <div v-for="item in metricCards" :key="item.label" class="bn-asset-tile">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </section>

      <!-- Trend + Priority Runs -->
      <section class="bn-mid-grid">
        <div class="bn-card">
          <div class="bn-card__head">
            <div>
              <h2>近 7 天成功率趋势</h2>
              <p>按任务创建时间汇总</p>
            </div>
            <span class="bn-pill bn-pill--blue">{{ trendOverview }}</span>
          </div>
          <TrendChart :data="trendSeries" :height="210" aria-label="最近 7 天成功率趋势" />
        </div>

        <div class="bn-card">
          <div class="bn-card__head">
            <div>
              <h2>待关注任务</h2>
              <p>失败、异常、超时或进行中</p>
            </div>
            <button type="button" class="bn-text-link" @click="$router.push('/execution/index')">查看全部 →</button>
          </div>
          <div class="bn-alert-list">
            <div v-for="item in priorityRuns" :key="item.id" class="bn-alert-row">
              <span class="bn-dot" :class="`bn-dot--${statusTone(item.status)}`" />
              <div class="bn-alert-row__info">
                <div class="bn-alert-row__name">{{ item.case_name }}</div>
                <small>{{ statusText(item.status) }} · {{ formatTime(item.created_at) }}</small>
              </div>
            </div>
            <el-empty v-if="!priorityRuns.length" description="暂无异常或卡滞任务" :image-size="64" />
          </div>
        </div>
      </section>

      <!-- Recent Activity Stream -->
      <section class="bn-card">
        <div class="bn-card__head bn-card__head--wrap">
          <div>
            <h2>最近执行流</h2>
            <p>共 {{ filteredRuns.length }} 条记录</p>
          </div>
          <div class="bn-filters">
            <el-select v-model="filters.status" clearable placeholder="状态" style="width: 124px">
              <el-option label="排队中" value="PENDING" />
              <el-option label="执行中" value="RUNNING" />
              <el-option label="成功" value="SUCCESS" />
              <el-option label="失败" value="FAILED" />
              <el-option label="异常" value="ERROR" />
              <el-option label="超时" value="TIMEOUT" />
            </el-select>
            <el-input v-model="filters.keyword" clearable placeholder="搜索用例名称…" style="width: 210px" />
          </div>
        </div>

        <div class="bn-stream">
          <div v-for="item in pagedRuns" :key="item.id" class="bn-stream-row">
            <div class="bn-stream-row__left">
              <span class="bn-dot" :class="`bn-dot--${statusTone(item.status)}`" />
              <div class="bn-stream-row__main">
                <div class="bn-stream-row__title">
                  <span>{{ item.case_name }}</span>
                  <span class="bn-type-tag">{{ item.case_type }}</span>
                </div>
                <div class="bn-stream-row__summary">{{ item.summary || '暂无摘要' }}</div>
              </div>
            </div>
            <div class="bn-stream-row__right">
              <span class="bn-status-chip" :class="`bn-status-chip--${statusTone(item.status)}`">
                {{ statusText(item.status) }}
              </span>
              <span class="bn-mono">{{ item.duration_ms ? `${item.duration_ms}ms` : '—' }}</span>
              <span class="bn-time">{{ formatTime(item.created_at) }}</span>
            </div>
          </div>
          <el-empty v-if="!pagedRuns.length" description="暂无最近执行记录" :image-size="64" />
        </div>

        <div class="bn-pagination">
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
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import TrendChart from '@/components/TrendChart.vue'
import { formatDateTime as formatTime } from '@/lib/formatTime'

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
const autoRefresh = ref(false)
const page = ref(1)
const pageSize = ref(8)
const filters = reactive({
  keyword: '',
  status: ''
})

const quickLinks = [
  { title: '接口用例', desc: '构建与调试 API 场景', path: '/case/api' },
  { title: '测试计划', desc: '编排回归与定时调度', path: '/plan/index' },
  { title: '执行中心', desc: '查看实时日志与产物', path: '/execution/index' },
  { title: '报告中心', desc: '质量趋势与失败聚合', path: '/report/index' }
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

const failedCount = computed(() => runs.value.filter((run) => ['FAILED', 'ERROR'].includes(run.status)).length)
const timeoutCount = computed(() => runs.value.filter((run) => run.status === 'TIMEOUT').length)
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

const statusItems = computed(() => ([
  { label: 'FastAPI 应用', value: statusText(health.value.app_status), hint: '核心接口服务', tone: statusTone(health.value.app_status) },
  { label: 'MariaDB 数据库', value: statusText(health.value.database), hint: '主存储连接', tone: statusTone(health.value.database) },
  { label: 'Redis 队列', value: statusText(health.value.redis), hint: '任务调度与缓存', tone: statusTone(health.value.redis) },
  { label: '最近同步', value: formatTime(health.value.checked_at) || '-', hint: loading.value ? '同步中' : (autoRefresh.value ? '10 秒自动刷新' : '手动刷新'), tone: loading.value ? 'warning' : 'neutral' }
]))

const priorityRuns = computed(() =>
  runs.value.filter((run) => ['FAILED', 'ERROR', 'TIMEOUT', 'PENDING', 'RUNNING'].includes(run.status)).slice(0, 5)
)

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

const trendSeries = computed(() =>
  trendData.value.map((item) => ({
    key: item.key,
    label: item.label,
    value: item.value,
    title: `${item.label} · 成功率 ${item.value}% · ${item.success}/${item.total}`
  }))
)

const trendOverview = computed(() => {
  const latest = trendData.value.at(-1)?.value || 0
  const previous = trendData.value.at(-2)?.value || 0
  const delta = latest - previous
  const sign = delta > 0 ? '+' : ''
  return `今日 ${latest}% (${sign}${delta}%)`
})

const successTrendText = computed(() => {
  const latest = trendData.value.at(-1)?.value || 0
  const previous = trendData.value.at(-2)?.value || 0
  const delta = latest - previous
  if (delta === 0) return '与昨日持平'
  return delta > 0 ? `较昨日 +${delta}%` : `较昨日 ${delta}%`
})

let timer = null

const loadAll = async (silent = false) => {
  if (silent && typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  if (!silent) loading.value = true
  try {
    const [summaryData, runData] = await Promise.all([
      api.get('/dashboard/summary'),
      api.get('/executions/runs')
    ])
    summary.value = summaryData
    runs.value = Array.isArray(runData) ? runData : (runData?.items || [])
    try {
      health.value = await api.get('/system/health')
    } catch {
      health.value = { app_status: 'degraded', database: 'unknown', redis: 'unknown', checked_at: '' }
    }
  } catch (error) {
    if (!silent) ElMessage.error(error.message)
  } finally {
    if (!silent) loading.value = false
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
  loadAll(false)
  timer = setInterval(() => {
    if (autoRefresh.value) loadAll(true)
  }, 10000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.bento-stage {
  min-height: calc(100vh - var(--app-header-height));
  background: transparent;
  padding: 24px 32px 36px;
}

.bento-container {
  max-width: 1320px;
  margin: 0 auto;
  display: grid;
  gap: 16px;
}

.bn-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.bn-kicker {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: #0071e3;
  margin-bottom: 4px;
}

.bn-title {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #1d1d1f;
}

.bn-subtitle {
  margin: 4px 0 0;
  font-size: 13.5px;
  color: #6e6e73;
}

.bn-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bn-switch-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  font-size: 12.5px;
  color: #6e6e73;
}

.bn-btn {
  height: 34px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: #ffffff;
  color: #1d1d1f;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.14s ease;
}

.bn-btn:hover { background: #fbfbfd; border-color: rgba(0, 0, 0, 0.16); }

.bn-btn--primary {
  border: none;
  background: #0071e3;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 113, 227, 0.25);
}

.bn-btn--primary:hover { background: #0077ed; }

.bn-shortcuts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.bn-shortcut {
  text-align: left;
  padding: 14px 16px;
  border-radius: 16px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(20px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  cursor: pointer;
  transition: transform 0.14s ease, box-shadow 0.14s ease, background 0.14s ease;
}

.bn-shortcut:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}

.bn-shortcut__title {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #1d1d1f;
}

.bn-shortcut__desc {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  color: #86868b;
}

.bn-top-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, 1fr);
  gap: 16px;
}

.bn-mid-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 1fr);
  gap: 16px;
}

.bn-card {
  border-radius: 20px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(22px) saturate(180%);
  padding: 20px 22px;
  box-shadow: var(--apple-glass-shadow);
}

.bn-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.bn-card__head--wrap { flex-wrap: wrap; }

.bn-card__head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.015em;
  color: #1d1d1f;
}

.bn-card__head p {
  margin: 2px 0 0;
  font-size: 12px;
  color: #86868b;
}

.bn-muted {
  font-size: 12px;
  color: #86868b;
}

.bn-pill {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
}

.bn-pill--green { background: rgba(52, 199, 89, 0.14); color: #248a3d; }
.bn-pill--amber { background: rgba(255, 159, 10, 0.14); color: #c96a00; }
.bn-pill--blue { background: rgba(0, 113, 227, 0.1); color: #0071e3; }

.bn-health-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.bn-health-item {
  padding: 12px 14px;
  border-radius: 14px;
  background: #f5f5f7;
}

.bn-health-item__top {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6e6e73;
}

.bn-health-item strong {
  display: block;
  margin-top: 6px;
  font-size: 15px;
  color: #1d1d1f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bn-health-item small {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #86868b;
}

.bn-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex-shrink: 0;
}

.bn-dot--success { background: #34c759; }
.bn-dot--warning { background: #ff9f0a; }
.bn-dot--danger { background: #ff3b30; }
.bn-dot--neutral { background: #0071e3; }

.bn-score-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.bn-score-num {
  font-size: 46px;
  font-weight: 700;
  letter-spacing: -0.04em;
  color: #1d1d1f;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.bn-score-num span {
  font-size: 18px;
  font-weight: 500;
  color: #86868b;
  margin-left: 2px;
}

.bn-score-bars {
  flex: 1;
  display: grid;
  gap: 8px;
}

.bn-mini-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-radius: 10px;
  background: #f5f5f7;
  font-size: 12.5px;
  color: #6e6e73;
}

.bn-mini-row strong {
  font-size: 14px;
  color: #1d1d1f;
  font-variant-numeric: tabular-nums;
}

.bn-mini-row strong.is-red { color: #d70015; }
.bn-mini-row strong.is-amber { color: #c96a00; }
.bn-mini-row strong.is-blue { color: #0071e3; }

.bn-assets-grid {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 10px;
}

.bn-asset-tile {
  padding: 12px 14px;
  border-radius: 14px;
  background: #f5f5f7;
  transition: background 0.14s ease;
}

.bn-asset-tile:hover { background: #ebebef; }

.bn-asset-tile span {
  display: block;
  font-size: 12px;
  color: #6e6e73;
}

.bn-asset-tile strong {
  display: block;
  margin-top: 6px;
  font-size: 22px;
  font-weight: 700;
  color: #1d1d1f;
  font-variant-numeric: tabular-nums;
}

.bn-text-link {
  border: none;
  background: transparent;
  color: #0071e3;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
}

.bn-alert-list {
  display: grid;
  gap: 8px;
}

.bn-alert-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f5f5f7;
}

.bn-alert-row__info { min-width: 0; flex: 1; }

.bn-alert-row__name {
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bn-alert-row__info small {
  font-size: 11.5px;
  color: #86868b;
}

.bn-filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bn-stream {
  display: grid;
}

.bn-stream-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 6px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.bn-stream-row:last-child { border-bottom: none; }

.bn-stream-row__left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.bn-stream-row__main { min-width: 0; flex: 1; }

.bn-stream-row__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 600;
  color: #1d1d1f;
}

.bn-stream-row__title span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bn-type-tag {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 5px;
  background: #f5f5f7;
  color: #6e6e73;
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
}

.bn-stream-row__summary {
  margin-top: 2px;
  font-size: 12px;
  color: #86868b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bn-stream-row__right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.bn-status-chip {
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
}

.bn-status-chip--success { background: rgba(52, 199, 89, 0.14); color: #248a3d; }
.bn-status-chip--warning { background: rgba(255, 159, 10, 0.14); color: #c96a00; }
.bn-status-chip--danger { background: rgba(255, 59, 48, 0.12); color: #d70015; }

.bn-mono,
.bn-time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: #6e6e73;
  font-variant-numeric: tabular-nums;
}

.bn-time { color: #86868b; }

.bn-pagination {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 1120px) {
  .bn-shortcuts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .bn-top-grid,
  .bn-mid-grid { grid-template-columns: 1fr; }
  .bn-assets-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .bn-health-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 720px) {
  .bento-stage { padding: 16px; }
  .bn-header { flex-direction: column; align-items: flex-start; }
  .bn-assets-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .bn-stream-row { flex-direction: column; align-items: flex-start; }
}
</style>
