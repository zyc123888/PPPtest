<template>
  <div class="app-page exec-page">
    <PageHeader title="执行中心" subtitle="实时追踪接口、UI 与性能任务流，点击任意行展开侧边诊断抽屉">
      <template #actions>
        <div class="exec-header-actions">
          <span v-if="hasActiveRuns" class="live-pill">
            <span class="live-pill__dot" />
            实时同步
          </span>
          <el-button :loading="listLoading" @click="getList">刷新</el-button>
        </div>
      </template>
    </PageHeader>

    <!-- Unified Hairline KPI Strip + Proportional Health Bar (Vercel / Linear pattern) -->
    <section class="overview-strip section-gap" aria-label="执行概览">
      <div class="overview-grid">
        <div class="overview-cell">
          <span class="overview-cell__label">总执行次数</span>
          <strong class="overview-cell__val">{{ total }}</strong>
        </div>
        <div class="overview-cell">
          <span class="overview-cell__label">
            <span class="mini-dot mini-dot--amber" :class="{ 'is-pulse': stats.running > 0 }" />
            进行中 / 排队
          </span>
          <strong class="overview-cell__val">{{ stats.running }}</strong>
        </div>
        <div class="overview-cell">
          <span class="overview-cell__label">
            <span class="mini-dot mini-dot--rose" />
            失败 / 异常
          </span>
          <strong class="overview-cell__val">{{ stats.failed }}</strong>
        </div>
        <div class="overview-cell">
          <span class="overview-cell__label">
            <span class="mini-dot mini-dot--emerald" />
            通过率（当前口径）
          </span>
          <strong class="overview-cell__val">{{ passRatePercent }}<small>%</small></strong>
        </div>
      </div>
      <div class="health-bar" role="img" aria-label="执行状态占比条">
        <span class="health-bar__seg health-bar__seg--success" :style="{ width: `${healthSegments.success}%` }" />
        <span class="health-bar__seg health-bar__seg--running" :style="{ width: `${healthSegments.running}%` }" />
        <span class="health-bar__seg health-bar__seg--failed" :style="{ width: `${healthSegments.failed}%` }" />
      </div>
    </section>

    <section class="surface-card">
      <!-- Segmented Status Tabs + Compact Filters (GitHub Actions / Linear pattern) -->
      <div class="toolbar-bar">
        <div class="seg-tabs" role="tablist" aria-label="状态筛选">
          <button
            v-for="tab in statusTabs"
            :key="tab.value"
            type="button"
            role="tab"
            class="seg-tab"
            :class="{ 'is-active': filters.status === tab.value }"
            @click="selectStatusTab(tab.value)"
          >
            <span>{{ tab.label }}</span>
            <span v-if="tab.count !== null" class="seg-tab__count">{{ tab.count }}</span>
          </button>
        </div>

        <div class="filter-controls">
          <el-select
            v-model="filters.projectId"
            clearable
            filterable
            placeholder="项目"
            class="ctrl-project"
            @change="handleSearch"
          >
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>

          <el-select
            v-model="filters.caseType"
            clearable
            placeholder="类型"
            class="ctrl-sm"
            @change="handleSearch"
          >
            <el-option label="API" value="API" />
            <el-option label="UI" value="UI" />
            <el-option label="PERF" value="PERF" />
          </el-select>

          <el-select
            v-model="filters.errorType"
            clearable
            placeholder="失败原因"
            class="ctrl-md"
            @change="handleSearch"
          >
            <el-option
              v-for="item in EXECUTION_ERROR_TYPE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>

          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="筛选用例名或摘要…"
            class="ctrl-search"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>

          <el-button v-if="hasActiveFilters" text size="small" @click="handleReset">重置</el-button>
        </div>
      </div>

      <!-- Contextual Selection Bar -->
      <div v-if="canTest && selectedRuns.length" class="selection-banner">
        <span class="selection-banner__text">已选中 <strong>{{ selectedRuns.length }}</strong> 条执行记录</span>
        <div class="selection-banner__actions">
          <el-button size="small" type="primary" @click="handleBatchRerun">批量重跑</el-button>
          <el-button
            v-if="cancellableSelectedRuns.length"
            size="small"
            type="danger"
            plain
            @click="handleBatchCancel"
          >
            批量取消 ({{ cancellableSelectedRuns.length }})
          </el-button>
        </div>
      </div>

      <el-table
        v-loading="listLoading"
        :data="list"
        class="geist-table"
        row-class-name="exec-row"
        @selection-change="handleSelectionChange"
        @row-click="handleRowClick"
      >
        <el-table-column type="selection" width="44" align="center" />

        <el-table-column label="执行" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="run-primary">
              <span
                class="state-dot"
                :class="[`state-dot--${statusTone(row.status)}`, { 'is-pulse': ['PENDING', 'RUNNING'].includes(row.status) }]"
                :title="statusText(row.status)"
              />
              <div class="run-primary__body">
                <div class="run-primary__top">
                  <span class="run-primary__name">{{ row.case_name }}</span>
                  <span class="type-tag">{{ row.case_type }}</span>
                </div>
                <div class="run-primary__meta">
                  <span class="mono-muted">#{{ row.id }}</span>
                  <span class="sep">·</span>
                  <span>{{ projectName(row.project_id) }}</span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="104">
          <template #default="{ row }">
            <span class="status-text" :class="`status-text--${statusTone(row.status)}`">
              {{ statusText(row.status) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="结果摘要" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="summary-cell">
              <span v-if="row.error_type" class="error-pill">{{ errorTypeText(row.error_type) }}</span>
              <span class="summary-cell__text">{{ row.summary || '—' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="耗时" width="96" align="right">
          <template #default="{ row }">
            <span class="mono-num">{{ row.duration_ms ? `${row.duration_ms}ms` : '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="时间" width="158" align="right">
          <template #default="{ row }">
            <span class="mono-time">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="" width="146" align="right" fixed="right">
          <template #default="{ row }">
            <div class="row-ops" @click.stop>
              <button type="button" class="op-link op-link--primary" @click="openInspector(row, 'steps')">详情</button>
              <button
                v-if="canCancel(row)"
                type="button"
                class="op-link op-link--danger"
                @click="handleCancel(row)"
              >
                取消
              </button>
              <button
                v-else-if="canTest"
                type="button"
                class="op-link"
                @click="handleRerun(row)"
              >
                重跑
              </button>
              <el-dropdown trigger="click" @command="(cmd) => handleRowCommand(cmd, row)">
                <button type="button" class="op-icon" aria-label="更多操作">
                  <el-icon><MoreFilled /></el-icon>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="logs">查看日志</el-dropdown-item>
                    <el-dropdown-item command="artifacts">查看产物</el-dropdown-item>
                    <el-dropdown-item v-if="canCancel(row) && canTest" command="rerun" divided>重跑</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in list" :key="item.id" class="mobile-card" @click="openInspector(item, 'steps')">
          <div class="mobile-card__head">
            <span class="state-dot" :class="`state-dot--${statusTone(item.status)}`" />
            <span class="mobile-card__title">{{ item.case_name }}</span>
            <span class="type-tag">{{ item.case_type }}</span>
          </div>
          <div class="mobile-card__meta">
            #{{ item.id }} · {{ projectName(item.project_id) }} · {{ statusText(item.status) }} · {{ item.duration_ms ? `${item.duration_ms}ms` : '—' }}
          </div>
          <div class="mobile-card__desc">{{ item.summary || '—' }}</div>
          <div class="mobile-card__actions" @click.stop>
            <button type="button" class="op-link op-link--primary" @click="openInspector(item, 'steps')">详情</button>
            <button type="button" class="op-link" @click="openInspector(item, 'logs')">日志</button>
            <button type="button" class="op-link" @click="openInspector(item, 'artifacts')">产物</button>
            <button v-if="canCancel(item)" type="button" class="op-link op-link--danger" @click="handleCancel(item)">取消</button>
            <button v-if="canTest" type="button" class="op-link" @click="handleRerun(item)">重跑</button>
          </div>
        </div>
      </div>

      <div class="surface-footer">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-sizes="[10, 20, 30]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </section>

    <!-- Unified Inspector Drawer with Visual Step Timeline -->
    <el-drawer
      v-model="inspectorVisible"
      size="720px"
      class="exec-drawer"
      :with-header="false"
      @closed="handleInspectorClosed"
    >
      <div class="drawer-shell">
        <header class="drawer-head">
          <div class="drawer-head__left">
            <div class="drawer-head__badges">
              <span class="mono-muted">#{{ currentRun.id }}</span>
              <span v-if="currentRun.case_type" class="type-tag">{{ currentRun.case_type }}</span>
              <span class="status-text" :class="`status-text--${statusTone(currentRun.status)}`">
                <span
                  class="mini-dot"
                  :class="[`mini-dot--${statusDotClass(currentRun.status)}`, { 'is-pulse': ['PENDING', 'RUNNING'].includes(currentRun.status) }]"
                />
                {{ statusText(currentRun.status) }}
              </span>
            </div>
            <h3 class="drawer-head__title">{{ currentRun.case_name || '执行详情' }}</h3>
          </div>

          <div class="drawer-head__actions">
            <div class="nav-group">
              <button type="button" class="nav-btn" :disabled="!canNavigatePrev" @click="navigateRun(-1)">上一条</button>
              <button type="button" class="nav-btn" :disabled="!canNavigateNext" @click="navigateRun(1)">下一条</button>
            </div>
            <el-button
              v-if="canCancel(currentRun)"
              size="small"
              type="danger"
              plain
              @click="handleCancel(currentRun)"
            >
              取消
            </el-button>
            <el-button
              v-if="canTest && currentRun.id"
              size="small"
              type="primary"
              @click="handleRerun(currentRun)"
            >
              重跑
            </el-button>
            <button type="button" class="close-btn" aria-label="关闭" @click="inspectorVisible = false">✕</button>
          </div>
        </header>

        <div class="drawer-meta-strip">
          <div class="meta-cell">
            <span>耗时</span>
            <strong class="mono-num">{{ currentRun.duration_ms ? `${currentRun.duration_ms}ms` : '—' }}</strong>
          </div>
          <div class="meta-cell">
            <span>错误类型</span>
            <strong>{{ currentRun.error_type ? errorTypeText(currentRun.error_type) : '—' }}</strong>
          </div>
          <div class="meta-cell">
            <span>退出码</span>
            <strong class="mono-num">{{ currentRun.exit_code ?? '—' }}</strong>
          </div>
          <div class="meta-cell">
            <span>超时阈值</span>
            <strong class="mono-num">{{ currentRun.timeout_seconds ? `${currentRun.timeout_seconds}s` : '—' }}</strong>
          </div>
          <div class="meta-cell">
            <span>重跑次数</span>
            <strong class="mono-num">{{ currentRun.retry_count || 0 }}</strong>
          </div>
        </div>

        <div v-if="isPrecheckFailure(currentRun)" class="precheck-callout">
          <div class="precheck-callout-title">执行前预检失败</div>
          <div class="precheck-callout-body">{{ currentRun.summary || '环境变量或模板配置校验未通过' }}</div>
        </div>

        <el-tabs v-model="inspectorTab" class="drawer-tabs" @tab-change="handleInspectorTabChange">
          <el-tab-pane label="步骤时间线" name="steps">
            <el-empty v-if="!currentSteps.length" description="暂无步骤明细" :image-size="68" />
            <template v-else>
              <ol class="step-timeline">
                <li v-for="step in currentSteps" :key="step.index" class="step-node">
                  <div class="step-node__rail">
                    <span class="state-dot" :class="`state-dot--${statusTone(step.status)}`" />
                    <span v-if="step.index < currentSteps.length" class="step-node__line" />
                  </div>
                  <div class="step-node__card">
                    <div class="step-node__head">
                      <span class="step-node__idx">{{ String(step.index).padStart(2, '0') }}</span>
                      <span class="step-node__name">{{ step.name }}</span>
                      <span class="step-node__dur mono-num">
                        {{ step.duration_ms ? `${step.duration_ms}ms` : '—' }}
                      </span>
                    </div>
                    <div v-if="step.duration_ms && maxStepDuration > 0" class="step-node__bar">
                      <span
                        class="step-node__bar-fill"
                        :class="`step-node__bar-fill--${statusTone(step.status)}`"
                        :style="{ width: `${Math.max(4, Math.round((step.duration_ms / maxStepDuration) * 100))}%` }"
                      />
                    </div>
                    <div v-if="step.detail" class="step-node__detail">
                      {{ formatStepDetail(step.detail) }}
                    </div>
                  </div>
                </li>
              </ol>

              <el-collapse class="raw-json-collapse">
                <el-collapse-item title="原始步骤 JSON" name="raw">
                  <pre class="code-block">{{ formatJson(currentRun.step_results_json) }}</pre>
                </el-collapse-item>
              </el-collapse>
            </template>
          </el-tab-pane>

          <el-tab-pane label="请求与响应" name="payload">
            <div class="payload-section">
              <div class="payload-section__head">
                <span>请求载荷</span>
                <button type="button" class="op-link" @click="copyText(formatJson(currentRun.request_payload))">复制</button>
              </div>
              <pre class="code-block">{{ formatJson(currentRun.request_payload) }}</pre>
            </div>
            <div class="payload-section">
              <div class="payload-section__head">
                <span>响应载荷</span>
                <button type="button" class="op-link" @click="copyText(formatJson(currentRun.response_payload))">复制</button>
              </div>
              <pre class="code-block">{{ formatJson(currentRun.response_payload) }}</pre>
            </div>
          </el-tab-pane>

          <el-tab-pane label="执行日志" name="logs">
            <div v-loading="logLoading" class="logs-pane">
              <div class="logs-switch">
                <el-radio-group v-model="logStream" size="small">
                  <el-radio-button value="stdout">标准输出</el-radio-button>
                  <el-radio-button value="stderr">错误输出</el-radio-button>
                </el-radio-group>
              </div>
              <LogTerminal
                :content="logStream === 'stdout' ? (logData.stdout_text || '') : (logData.stderr_text || '')"
                @copy="copyText"
              />
            </div>
          </el-tab-pane>

          <el-tab-pane :label="artifactTabLabel" name="artifacts">
            <div v-loading="artifactLoading">
              <el-empty v-if="!artifactData.length" description="暂无执行产物" :image-size="68" />
              <div v-else class="artifact-list">
                <div v-for="(item, index) in artifactData" :key="`${item.path}-${index}`" class="artifact-item">
                  <div class="artifact-info">
                    <div class="artifact-name">{{ item.name }}</div>
                    <div class="artifact-path">{{ item.path }}</div>
                  </div>
                  <div class="artifact-actions">
                    <el-button size="small" @click="downloadArtifact(index, item)">下载</el-button>
                    <button type="button" class="op-link" @click="copyArtifactPath(item.path)">复制路径</button>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { getSavedProjectId, saveActiveProjectId } from '@/lib/projectContext'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled, Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import LogTerminal from '@/components/LogTerminal.vue'
import { usePermissions } from '@/lib/permissions'
import { formatDateTime as formatTime } from '@/lib/formatTime'
import {
  EXECUTION_ERROR_TYPE_OPTIONS,
  executionErrorTypeText,
  isValidRunId,
  executionStatusText
} from '@/lib/execution'

const list = ref([])
const total = ref(0)
const stats = reactive({ running: 0, failed: 0, retryable: 0 })
const projects = ref([])
const selectedRuns = ref([])
const cancellableSelectedRuns = computed(() =>
  selectedRuns.value.filter((item) => ['PENDING', 'RUNNING'].includes(item.status))
)
const handleSelectionChange = (rows) => {
  selectedRuns.value = rows || []
}
const listLoading = ref(true)
const inspectorVisible = ref(false)
const inspectorTab = ref('steps')
const logStream = ref('stdout')
const logLoading = ref(false)
const artifactLoading = ref(false)
const currentRun = ref({})
const logData = ref({})
const artifactData = ref([])
const artifactRunId = ref(null)
const loadedLogRunId = ref(null)
const loadedArtifactRunId = ref(null)
const { canTest } = usePermissions()
const route = useRoute()
const router = useRouter()
let timer = null
let runEventSource = null

const filters = reactive({
  projectId: '',
  status: '',
  caseType: '',
  errorType: '',
  keyword: ''
})

const page = ref(1)
const pageSize = ref(20)

const statusText = executionStatusText
const errorTypeText = executionErrorTypeText

const statusTone = (status) => {
  if (status === 'SUCCESS') return 'success'
  if (['FAILED', 'ERROR', 'TIMEOUT'].includes(status)) return 'danger'
  if (status === 'RUNNING') return 'info'
  if (status === 'PENDING') return 'warning'
  return 'muted'
}

const statusDotClass = (status) => {
  const tone = statusTone(status)
  if (tone === 'success') return 'emerald'
  if (tone === 'danger') return 'rose'
  if (tone === 'warning' || tone === 'info') return 'amber'
  return 'slate'
}

const isPrecheckFailure = (payload) => payload?.error_type === 'CONFIG'
const canCancel = (row) => canTest.value && ['PENDING', 'RUNNING'].includes(row?.status)
const projectName = (id) => projects.value.find((item) => item.id === id)?.name || `#${id}`

const successEstimate = computed(() => Math.max(0, total.value - stats.running - stats.failed))
const passRatePercent = computed(() => {
  const finished = total.value - stats.running
  if (finished <= 0) return 0
  return Math.round((successEstimate.value / finished) * 100)
})

const healthSegments = computed(() => {
  if (!total.value) return { success: 0, running: 0, failed: 0 }
  return {
    success: Math.round((successEstimate.value / total.value) * 100),
    running: Math.round((stats.running / total.value) * 100),
    failed: Math.round((stats.failed / total.value) * 100)
  }
})

const statusTabs = computed(() => [
  { label: '全部', value: '', count: total.value },
  { label: '排队中', value: 'PENDING', count: stats.running || null },
  { label: '失败', value: 'FAILED', count: stats.failed || null },
  { label: '成功', value: 'SUCCESS', count: null }
])

const hasActiveFilters = computed(() =>
  Boolean(filters.projectId || filters.status || filters.caseType || filters.errorType || filters.keyword.trim())
)

const artifactTabLabel = computed(() =>
  artifactData.value.length ? `执行产物 (${artifactData.value.length})` : '执行产物'
)

const currentRunIndex = computed(() => list.value.findIndex((item) => item.id === currentRun.value?.id))
const canNavigatePrev = computed(() => currentRunIndex.value > 0)
const canNavigateNext = computed(() => currentRunIndex.value >= 0 && currentRunIndex.value < list.value.length - 1)

const formatJson = (val) => {
  if (!val) return '{}'
  try {
    return JSON.stringify(val, null, 2)
  } catch {
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
  if (detail === null || detail === undefined || detail === '') return ''
  if (typeof detail === 'string') return detail
  try {
    return JSON.stringify(detail)
  } catch {
    return String(detail)
  }
}

const currentSteps = computed(() => normalizeSteps(currentRun.value.step_results_json))
const maxStepDuration = computed(() =>
  currentSteps.value.reduce((max, s) => Math.max(max, Number(s.duration_ms) || 0), 0)
)

const getList = async (options = {}) => {
  const silent = options?.silent === true
  if (silent && typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  if (!silent) listLoading.value = true
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) })
    if (filters.projectId) params.set('project_id', String(filters.projectId))
    if (filters.caseType) params.set('case_type', filters.caseType)
    if (filters.status) params.set('status', filters.status)
    if (filters.errorType) params.set('error_type', filters.errorType)
    if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
    const data = await api.get(`/executions/runs?${params.toString()}`)
    list.value = data.items || []
    total.value = data.total || 0
    stats.running = data.running || 0
    stats.failed = data.failed || 0
    stats.retryable = data.retryable || 0
  } catch (error) {
    if (!silent) ElMessage.error(error.message)
  } finally {
    if (!silent) listLoading.value = false
  }
}

const fetchProjects = async () => {
  try {
    projects.value = await api.get('/projects')
    if (!filters.projectId) {
      const saved = getSavedProjectId(projects.value)
      if (saved) filters.projectId = saved
    }
  } catch {
    projects.value = []
  }
}

watch(() => filters.projectId, (val) => {
  saveActiveProjectId(val)
})

const hasActiveRuns = computed(() => list.value.some((item) => ['PENDING', 'RUNNING'].includes(item.status)))

const restartTimer = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (!hasActiveRuns.value) return
  timer = setInterval(() => getList({ silent: true }), 5000)
}

watch([page, pageSize], () => {
  getList()
})

const handleSearch = () => {
  if (page.value === 1) {
    getList()
  } else {
    page.value = 1
  }
}

const selectStatusTab = (val) => {
  filters.status = val
  handleSearch()
}

const handleReset = () => {
  filters.projectId = ''
  filters.status = ''
  filters.caseType = ''
  filters.errorType = ''
  filters.keyword = ''
  handleSearch()
}

const closeRunStream = () => {
  if (runEventSource) {
    runEventSource.close()
    runEventSource = null
  }
}

const subscribeRunStream = (runId) => {
  closeRunStream()
  if (typeof EventSource === 'undefined') return
  const es = new EventSource(`/api/v1/executions/runs/${runId}/stream`, { withCredentials: true })
  runEventSource = es
  es.onmessage = async (event) => {
    if (runEventSource !== es) return
    try {
      const payload = JSON.parse(event.data)
      if (currentRun.value && currentRun.value.id === payload.id) {
        currentRun.value = { ...currentRun.value, ...payload }
      }
      if (['SUCCESS', 'FAILED', 'ERROR', 'TIMEOUT', 'CANCELLED'].includes(payload.status)) {
        closeRunStream()
        if (inspectorVisible.value && currentRun.value?.id === payload.id) {
          const data = await api.get(`/executions/runs/${payload.id}`)
          if (!inspectorVisible.value || currentRun.value?.id !== payload.id) return
          currentRun.value = data
          if (inspectorTab.value === 'logs') await fetchLogs(payload.id, true)
          if (inspectorTab.value === 'artifacts') await fetchArtifacts(payload.id, true)
        }
        getList()
      }
    } catch {
      // ignore malformed SSE chunk
    }
  }
  es.onerror = () => {
    if (runEventSource === es) closeRunStream()
  }
}

let inspectorRequest = 0
let logRequest = 0
let artifactRequest = 0

const fetchLogs = async (runId, force = false) => {
  if (!runId) return
  if (!force && loadedLogRunId.value === runId) return
  const request = ++logRequest
  const isCurrent = () => request === logRequest && currentRun.value?.id === runId
  logLoading.value = true
  try {
    const data = await api.get(`/executions/runs/${runId}/logs`)
    if (!isCurrent()) return
    logData.value = data
    loadedLogRunId.value = runId
  } catch (error) {
    if (isCurrent()) ElMessage.error(error.message)
  } finally {
    if (isCurrent()) logLoading.value = false
  }
}

const fetchArtifacts = async (runId, force = false) => {
  if (!runId) return
  if (!force && loadedArtifactRunId.value === runId) return
  const request = ++artifactRequest
  const isCurrent = () => request === artifactRequest && currentRun.value?.id === runId
  artifactLoading.value = true
  try {
    const data = await api.get(`/executions/runs/${runId}/artifacts`)
    if (!isCurrent()) return
    artifactRunId.value = runId
    artifactData.value = data.artifacts || []
    loadedArtifactRunId.value = runId
  } catch (error) {
    if (isCurrent()) ElMessage.error(error.message)
  } finally {
    if (isCurrent()) artifactLoading.value = false
  }
}

const openInspector = async (row, tab = 'steps') => {
  const request = ++inspectorRequest
  try {
    const data = await api.get(`/executions/runs/${row.id}`)
    if (request !== inspectorRequest) return
    if (currentRun.value?.id !== data.id) {
      logRequest += 1
      artifactRequest += 1
      logLoading.value = false
      artifactLoading.value = false
    }
    currentRun.value = data
    inspectorTab.value = tab
    logStream.value = 'stdout'
    if (loadedLogRunId.value !== data.id) {
      logData.value = {}
      loadedLogRunId.value = null
    }
    if (loadedArtifactRunId.value !== data.id) {
      artifactData.value = []
      loadedArtifactRunId.value = null
    }
    inspectorVisible.value = true
    if (['PENDING', 'RUNNING'].includes(data.status)) {
      subscribeRunStream(data.id)
    } else {
      closeRunStream()
    }
    if (tab === 'logs') await fetchLogs(data.id)
    if (tab === 'artifacts') await fetchArtifacts(data.id)
  } catch (error) {
    if (request === inspectorRequest) ElMessage.error(error.message)
  }
}

const handleInspectorTabChange = (tabName) => {
  if (!currentRun.value?.id) return
  if (tabName === 'logs') fetchLogs(currentRun.value.id)
  if (tabName === 'artifacts') fetchArtifacts(currentRun.value.id)
}

const handleRowClick = (row, column) => {
  if (column?.type === 'selection') return
  openInspector(row, 'steps')
}

const handleRowCommand = (command, row) => {
  if (command === 'logs') openInspector(row, 'logs')
  else if (command === 'artifacts') openInspector(row, 'artifacts')
  else if (command === 'rerun') handleRerun(row)
}

const navigateRun = (offset) => {
  const nextIdx = currentRunIndex.value + offset
  if (nextIdx < 0 || nextIdx >= list.value.length) return
  openInspector(list.value[nextIdx], inspectorTab.value)
}

const handleInspectorClosed = () => {
  closeRunStream()
  if (route.query.run_id) {
    const query = { ...route.query }
    delete query.run_id
    router.replace({ query })
  }
}

const openRunFromQuery = async (runId) => {
  if (!isValidRunId(runId)) {
    if (runId) ElMessage.error('执行编号无效')
    return
  }
  await openInspector({ id: Number(runId) }, 'steps')
}

const handleRerun = async (row) => {
  try {
    await ElMessageBox.confirm(`确认重跑执行 #${row.id}（${row.case_name}）？`, '重跑执行', {
      type: 'warning',
      confirmButtonText: '确认重跑',
      cancelButtonText: '取消'
    })
    await api.post(`/executions/runs/${row.id}/rerun`, {})
    ElMessage.success('重跑任务已提交')
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
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

const handleBatchRerun = async () => {
  if (!selectedRuns.value.length) return
  try {
    await ElMessageBox.confirm(`确认批量重跑选中的 ${selectedRuns.value.length} 条执行记录？`, '批量重跑', {
      type: 'warning',
      confirmButtonText: '确认重跑',
      cancelButtonText: '取消'
    })
    const res = await api.post('/executions/runs/batch-rerun', {
      run_ids: selectedRuns.value.map((r) => r.id)
    })
    ElMessage.success(res.message || '批量重跑已提交')
    selectedRuns.value = []
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const handleBatchCancel = async () => {
  if (!cancellableSelectedRuns.value.length) return
  try {
    await ElMessageBox.confirm(`确认批量取消选中的 ${cancellableSelectedRuns.value.length} 条进行中任务？`, '批量取消', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '关闭'
    })
    const res = await api.post('/executions/runs/batch-cancel', {
      run_ids: cancellableSelectedRuns.value.map((r) => r.id)
    })
    ElMessage.success(res.message || '批量取消成功')
    selectedRuns.value = []
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const copyText = async (text) => {
  if (!text) {
    ElMessage.info('无可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const copyArtifactPath = async (path) => {
  try {
    await navigator.clipboard.writeText(path)
    ElMessage.success('路径已复制')
  } catch {
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

onMounted(async () => {
  await fetchProjects()
  await getList()
  openRunFromQuery(route.query.run_id)
  restartTimer()
})

watch(() => route.query.run_id, (runId) => {
  if (runId) openRunFromQuery(runId)
})

watch(hasActiveRuns, () => {
  restartTimer()
})

onBeforeUnmount(() => {
  closeRunStream()
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.exec-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid #e4e4e7;
  background: #ffffff;
  color: #3f3f46;
  font-size: 12px;
  font-weight: 500;
}

.live-pill__dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #16a34a;
  animation: pulse-ring 1.6s ease-out infinite;
}

/* Apple Liquid Glass Overview Strip */
.overview-strip {
  border-radius: 18px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(22px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  overflow: hidden;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.overview-cell {
  padding: 14px 18px;
  border-right: 1px solid var(--color-border);
}

.overview-cell:last-child {
  border-right: none;
}

.overview-cell__label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #71717a;
}

.overview-cell__val {
  display: block;
  margin-top: 6px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1.1;
  color: #09090b;
  font-variant-numeric: tabular-nums;
}

.overview-cell__val small {
  font-size: 13px;
  font-weight: 500;
  color: #71717a;
  margin-left: 2px;
}

.health-bar {
  display: flex;
  height: 3px;
  width: 100%;
  background: #f4f4f5;
}

.health-bar__seg {
  height: 100%;
  transition: width 0.3s ease;
}

.health-bar__seg--success { background: #16a34a; }
.health-bar__seg--running { background: #d97706; }
.health-bar__seg--failed { background: #dc2626; }

.mini-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  display: inline-block;
}

.mini-dot--emerald { background: #16a34a; }
.mini-dot--amber { background: #d97706; }
.mini-dot--rose { background: #dc2626; }
.mini-dot--slate { background: #71717a; }
.mini-dot.is-pulse { animation: pulse-ring 1.6s ease-out infinite; }

.surface-card {
  border-radius: 20px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(24px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  overflow: hidden;
}

.toolbar-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.055);
  background: rgba(255, 255, 255, 0.45);
}

/* Apple Segmented Control */
.seg-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.055);
}

.seg-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #6e6e73;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.14s ease, color 0.14s ease, box-shadow 0.14s ease;
}

.seg-tab:hover {
  color: #1d1d1f;
}

.seg-tab.is-active {
  background: #ffffff;
  color: #1d1d1f;
  font-weight: 600;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.seg-tab__count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #71717a;
  font-variant-numeric: tabular-nums;
}

.filter-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ctrl-project { width: 156px; }
.ctrl-sm { width: 88px; }
.ctrl-md { width: 114px; }
.ctrl-search { width: 200px; }

.selection-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid #e4e4e7;
  background: #f4f4f5;
  font-size: 12.5px;
  color: #27272a;
}

.selection-banner__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Geist / Linear Table */
.geist-table {
  --el-table-border-color: #f4f4f5;
  --el-table-header-bg-color: #ffffff;
  --el-table-row-hover-bg-color: #fafafa;
}

.geist-table :deep(th.el-table__cell) {
  font-size: 11.5px;
  font-weight: 500;
  color: #71717a;
  padding: 9px 0;
  border-bottom: 1px solid var(--color-border);
}

.geist-table :deep(td.el-table__cell) {
  padding: 10px 0;
}

.geist-table :deep(.exec-row) {
  cursor: pointer;
}

.run-primary {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.run-primary__body {
  min-width: 0;
  flex: 1;
}

.run-primary__top {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.run-primary__name {
  font-size: 13px;
  font-weight: 500;
  color: #09090b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-primary__meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 2px;
  font-size: 12px;
  color: #71717a;
}

.sep {
  color: #d4d4d8;
}

.state-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex-shrink: 0;
}

.state-dot--success { background: #16a34a; }
.state-dot--danger { background: #dc2626; }
.state-dot--warning { background: #d97706; }
.state-dot--info { background: #2563eb; }
.state-dot--muted { background: #a1a1aa; }
.state-dot.is-pulse { animation: pulse-ring 1.6s ease-out infinite; }

.type-tag {
  flex-shrink: 0;
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid #e4e4e7;
  background: #fafafa;
  color: #52525b;
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 500;
}

.status-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
}

.status-text--success { color: #15803d; }
.status-text--danger { color: #b91c1c; }
.status-text--warning { color: #b45309; }
.status-text--info { color: #1d4ed8; }
.status-text--muted { color: #71717a; }

.mono-muted,
.mono-num,
.mono-time {
  font-family: var(--font-mono);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.mono-muted { color: #71717a; }
.mono-num { color: #3f3f46; }
.mono-time { color: #71717a; }

.summary-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.error-pill {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 11px;
  font-weight: 500;
}

.summary-cell__text {
  font-size: 12.5px;
  color: #52525b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Hover-revealed Row Actions (Linear / Vercel style) */
.row-ops {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  white-space: nowrap;
  opacity: 0.35;
  transition: opacity 0.14s ease;
}

.geist-table :deep(.exec-row:hover) .row-ops {
  opacity: 1;
}

.op-link {
  border: none;
  background: transparent;
  padding: 3px 6px;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 500;
  color: #52525b;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}

.op-link:hover {
  background: #f4f4f5;
  color: #09090b;
}

.op-link--primary { color: #0071e3; }
.op-link--primary:hover { background: rgba(0, 113, 227, 0.1); color: #0071e3; }
.op-link--danger { color: #d70015; }
.op-link--danger:hover { background: rgba(255, 59, 48, 0.1); color: #d70015; }

.op-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #71717a;
  cursor: pointer;
}

.op-icon:hover {
  background: #f4f4f5;
  color: #09090b;
}

.surface-footer {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
  background: #fafafa;
}

/* Inspector Drawer */
.drawer-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 20px 22px;
  box-sizing: border-box;
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--color-border);
}

.drawer-head__badges {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.drawer-head__title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: #09090b;
  line-height: 1.35;
}

.drawer-head__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.nav-group {
  display: inline-flex;
  border: 1px solid #e4e4e7;
  border-radius: 6px;
  overflow: hidden;
}

.nav-btn {
  height: 26px;
  padding: 0 9px;
  border: none;
  background: #ffffff;
  color: #3f3f46;
  font-size: 12px;
  cursor: pointer;
}

.nav-btn + .nav-btn {
  border-left: 1px solid #e4e4e7;
}

.nav-btn:hover:not(:disabled) {
  background: #fafafa;
  color: #09090b;
}

.nav-btn:disabled {
  color: #d4d4d8;
  cursor: not-allowed;
}

.close-btn {
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #71717a;
  font-size: 13px;
  cursor: pointer;
}

.close-btn:hover {
  background: #f4f4f5;
  color: #09090b;
}

.drawer-meta-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 14px 0;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: #fafafa;
  overflow: hidden;
}

.meta-cell {
  padding: 9px 12px;
  border-right: 1px solid var(--color-border);
}

.meta-cell:last-child {
  border-right: none;
}

.meta-cell span {
  display: block;
  font-size: 11px;
  color: #71717a;
}

.meta-cell strong {
  display: block;
  margin-top: 3px;
  font-size: 13px;
  font-weight: 600;
  color: #09090b;
}

.drawer-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.drawer-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: auto;
}

/* Visual Step Timeline Waterfall */
.step-timeline {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.step-node {
  display: flex;
  gap: 12px;
}

.step-node__rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 12px;
  width: 14px;
  flex-shrink: 0;
}

.step-node__line {
  width: 1px;
  flex: 1;
  min-height: 18px;
  margin-top: 5px;
  background: #e4e4e7;
}

.step-node__card {
  flex: 1;
  min-width: 0;
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: #ffffff;
}

.step-node__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-node__idx {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #a1a1aa;
}

.step-node__name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: #09090b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-node__dur {
  flex-shrink: 0;
  color: #71717a;
}

.step-node__bar {
  margin-top: 7px;
  height: 3px;
  border-radius: 999px;
  background: #f4f4f5;
  overflow: hidden;
}

.step-node__bar-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
}

.step-node__bar-fill--success { background: #16a34a; }
.step-node__bar-fill--danger { background: #dc2626; }
.step-node__bar-fill--warning { background: #d97706; }
.step-node__bar-fill--info { background: #2563eb; }
.step-node__bar-fill--muted { background: #a1a1aa; }

.step-node__detail {
  margin-top: 7px;
  padding: 7px 9px;
  border-radius: 6px;
  background: #fafafa;
  color: #52525b;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.5;
  word-break: break-all;
}

.payload-section {
  margin-bottom: 14px;
}

.payload-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #52525b;
}

.code-block {
  margin: 0;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid #e4e4e7;
  background: #fafafa;
  color: #18181b;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.logs-switch {
  margin-bottom: 10px;
}

.artifact-list {
  display: grid;
  gap: 8px;
}

.artifact-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: #ffffff;
}

.artifact-info {
  min-width: 0;
}

.artifact-name {
  font-size: 13px;
  font-weight: 500;
  color: #09090b;
}

.artifact-path {
  margin-top: 2px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: #71717a;
  word-break: break-all;
}

.artifact-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.raw-json-collapse {
  margin-top: 12px;
}

.precheck-callout {
  margin-bottom: 12px;
  border: 1px solid #fecaca;
  background: #fef2f2;
  border-radius: 8px;
  padding: 10px 12px;
}

.precheck-callout-title {
  color: #b91c1c;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}

.precheck-callout-body {
  color: #7f1d1d;
  font-size: 12px;
  line-height: 1.5;
}

.mobile-cards {
  display: none;
}

@keyframes pulse-ring {
  0% { box-shadow: 0 0 0 0 rgba(217, 119, 6, 0.4); }
  70% { box-shadow: 0 0 0 5px rgba(217, 119, 6, 0); }
  100% { box-shadow: 0 0 0 0 rgba(217, 119, 6, 0); }
}

@media (max-width: 960px) {
  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-cell {
    border-bottom: 1px solid var(--color-border);
  }

  .ctrl-project,
  .ctrl-sm,
  .ctrl-md,
  .ctrl-search {
    width: 100%;
  }

  .geist-table {
    display: none;
  }

  .mobile-cards {
    display: grid;
    gap: 10px;
    padding: 12px;
  }

  .mobile-card {
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 12px 14px;
    background: #ffffff;
  }

  .mobile-card__head {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .mobile-card__title {
    flex: 1;
    min-width: 0;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-card__meta {
    margin-top: 6px;
    font-size: 12px;
    color: #71717a;
  }

  .mobile-card__desc {
    margin-top: 6px;
    font-size: 12.5px;
    color: #52525b;
  }

  .mobile-card__actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #f4f4f5;
  }

  .drawer-meta-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
