<template>
  <div class="app-page case-generator-page">
    <PageHeader title="用例生成2" subtitle="V2 unified skill 流程，支持轻量模式和可信模式。">
      <template #actions>
        <div class="header-actions">
          <el-button @click="fetchJobs">刷新</el-button>
          <el-button type="primary" :loading="submitting" :disabled="submitDisabled" @click="submitJob">开始生成</el-button>
        </div>
      </template>
    </PageHeader>

    <el-alert
      v-if="pageError"
      class="page-error-alert"
      :title="pageError"
      type="warning"
      show-icon
      :closable="false"
    />

    <div class="generator-layout">
      <GeneratorConfigForm
        v-model:form="form"
        v-model:model-config="modelConfig"
        :projects="projects"
        :grouped-model-options="groupedModelOptions"
        :saving-model-config="savingModelConfig"
        :uploaded-file-name="uploadedFileName"
        :uploaded-char-count="uploadedCharCount"
        @load-model-config="loadModelConfig"
        @save-model-config="saveModelConfig"
        @file-change="handleFileChange"
      />

      <div class="generator-side">
        <JobHistoryPanel
          v-model:mode-filter="jobModeFilter"
          v-model:status-filter="jobStatusFilter"
          :jobs="jobList"
          :total-jobs="jobs.length"
          :pinned-running-job="pinnedRunningJob"
          :current-job-id="currentJob?.id"
          :has-more="jobsHasMore"
          :loading-more="loadingMoreJobs"
          @refresh="fetchJobs"
          @select-job="selectJob"
          @load-more="loadMoreJobs"
        />

        <JobDetailPanel
          v-model:active-artifact-type="activeArtifactType"
          :job="currentJob"
          :pipeline-mode="currentPipelineMode"
          :trusted="isTrustedCurrentJob"
          :can-rerun="canRerunCurrentJob"
          :can-cancel="canCancelCurrentJob"
          :rerunning="rerunning"
          :rerun-disabled="rerunDisabled"
          :cancelling="cancelling"
          :rerunning-shard="rerunningShard"
          :scope-index-strategy-text="scopeIndexStrategyText"
          :final-delivery-gate-passed="finalDeliveryGatePassed"
          :generation-metrics="generationMetrics"
          :metrics-comparison="metricsComparison"
          :trusted-metrics="trustedMetrics"
          :gate-issues="trustedGateIssues"
          :sources="sourcesDetail || []"
          :progress-status-text="progressStatusText"
          :progress-percent="progressPercent"
          :active-execution-proof="activeExecutionProof"
          :progress-stages="displayProgressStageItems"
          :stage-summaries="stageSummaries"
          :artifacts="visibleArtifacts"
          :active-artifact="activeArtifact"
          :final-xmind-artifact="finalXmindArtifact"
          :export-log-artifact="exportLogArtifact"
          :artifact-loading="artifactLoading"
          @rerun-job="rerunJob"
          @cancel-job="cancelJob"
          @refresh="refreshCurrentJob"
          @rerun-source="rerunSourceShard"
          @download-artifact="downloadArtifact"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import GeneratorConfigForm from './components/GeneratorConfigForm.vue'
import JobDetailPanel from './components/JobDetailPanel.vue'
import JobHistoryPanel from './components/JobHistoryPanel.vue'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import {
  cancelCaseGenerationV2Job,
  createCaseGenerationV2Job,
  getCaseGenerationV2ModelConfig,
  getCaseGenerationV2MetricsComparison,
  getCaseGenerationV2Artifact,
  downloadCaseGenerationV2Artifact,
  getCaseGenerationV2JobDetail,
  listCaseGenerationV2Jobs,
  listCaseGenerationV2ModelOptions,
  rerunCaseGenerationV2Job,
  rerunCaseGenerationV2SourceShard,
  saveCaseGenerationV2ModelConfig
} from '@/lib/caseGenerationV2'
import {
  nextPollingDelay,
  normalizeModelOptions,
  normalizePipelineMode,
  validateRequirementFile
} from '@/lib/caseGenerationUi'
import {
  buildTrustedGateIssues,
  canRerunSourceShard,
  filterVisibleArtifacts,
  formatDurationMs,
  formatScopeIndexStrategy,
  jobPipelineMode,
  resolveFinalDeliveryGatePassed
} from './presentation'

const projects = ref([])
const jobs = ref([])
const allJobs = ref([])
const currentJob = ref(null)
const currentArtifacts = ref([])
const currentAttempts = ref([])
const metricsComparison = ref(null)
const activeArtifactType = ref('')
const artifactLoading = ref(false)
const submitting = ref(false)
const rerunning = ref(false)
const rerunningShard = ref('')
const cancelling = ref(false)
const savingModelConfig = ref(false)
const hasSavedModelConfig = ref(false)
const authStore = useAuthStore()

const form = ref({
  project_id: null,
  name: '',
  mode: 'MARKDOWN',
  pipeline_mode: 'lite',
  trusted_generation_strategy: 'source_shard',
  generation_density: 'balanced',
  source_type: 'PASTE',
  source_document_name: '',
  source_url: '',
  markdown_text: '',
  export_xmind: true
})
const modelConfig = ref({
  name: '默认模型配置',
  api_key: '',
  model: 'gpt-5.5',
  base_url: ''
})
const uploadedFileName = ref('')
const uploadedCharCount = ref(0)
const pageError = ref('')
const jobStatusFilter = ref('')
const jobModeFilter = ref('')
const jobsHasMore = ref(false)
const loadingMoreJobs = ref(false)

const modelOptions = ref([])
const groupedModelOptions = computed(() => {
  const groups = new Map()
  for (const item of modelOptions.value) {
    if (!groups.has(item.provider)) {
      groups.set(item.provider, [])
    }
    groups.get(item.provider).push(item)
  }
  return Array.from(groups.entries()).map(([label, options]) => ({ label, options }))
})

const currentPipelineMode = computed(() => jobPipelineMode(currentJob.value))
const isTrustedCurrentJob = computed(() => normalizePipelineMode(currentPipelineMode.value) === 'trusted')
const trustedReviewArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'trusted_review_report'))
const trustedMetrics = computed(() => trustedReviewArtifact.value?.content_json?.summary || null)
const generationMetricsArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'generation_metrics'))
const generationMetrics = computed(() => metricsComparison.value?.candidate || generationMetricsArtifact.value?.content_json || null)
const scopeIndexArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'scope_index'))
const scopeIndexStrategy = computed(() => scopeIndexArtifact.value?.content_json?.execution_strategy || null)
const scopeIndexStrategyText = computed(() => formatScopeIndexStrategy(scopeIndexStrategy.value))
const finalDeliveryGateArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'final_delivery_gate'))
const finalDeliveryGatePassed = computed(() => resolveFinalDeliveryGatePassed(finalDeliveryGateArtifact.value, trustedMetrics.value))
const sourcesDetail = computed(() => trustedReviewArtifact.value?.content_json?.sources_detail || null)
const trustedGateIssues = computed(() =>
  isTrustedCurrentJob.value
    ? buildTrustedGateIssues(currentArtifacts.value, progressStageLabels)
    : []
)
const visibleArtifacts = computed(() => filterVisibleArtifacts(currentArtifacts.value, isTrustedCurrentJob.value))
const activeArtifact = computed(() =>
  visibleArtifacts.value.find((item) => item.artifact_type === activeArtifactType.value) || visibleArtifacts.value[0] || null
)
const finalXmindArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'xmind'))
const exportLogArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'xmind_export_log'))
const canRerunCurrentJob = computed(() => !!currentJob.value)
const rerunDisabled = computed(() => rerunning.value || !currentJob.value || ['RUNNING', 'PENDING'].includes(currentJob.value.status))
const currentUserId = computed(() => authStore.user?.id || null)
const activeAttempt = computed(() => currentAttempts.value.find((item) => item.id === currentJob.value?.active_attempt_id) || currentAttempts.value[0] || null)

const pinnedRunningJob = computed(() => jobs.value.find((item) => ['RUNNING', 'PENDING'].includes(item.status)))
const jobList = computed(() => jobs.value.filter((item) => item.id !== pinnedRunningJob.value?.id))
const activeOwnJob = computed(() =>
  allJobs.value.find((item) => item.created_by === currentUserId.value && ['RUNNING', 'PENDING'].includes(item.status))
)
const submitDisabled = computed(() => submitting.value || !!activeOwnJob.value)
const canCancelCurrentJob = computed(
  () =>
    !!currentJob.value &&
    currentJob.value.created_by === currentUserId.value &&
    ['RUNNING', 'PENDING'].includes(currentJob.value.status)
)
const stageSummaries = computed(() => [...(currentJob.value?.progress_json?.stages || [])].reverse())
const latestStageActivity = computed(() => {
  const stages = currentJob.value?.progress_json?.stages || []
  const latest = stages
    .filter((item) => item?.updated_at)
    .slice()
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
  return latest || null
})
const cloneProgressStageKeys = ['collect', 'image_analysis', 'requirement', 'testcase', 'review', 'export']
const trustedProgressStageKeys = ['orchestrate', 'evidence_trace', 'scope_index', 'scope_index_gate', 'requirement', 'requirement_gate', 'testcase_by_source_shard', 'testcase_gate', 'quality_review', 'export', 'final_delivery_gate']
const progressStageKeys = computed(() => (isTrustedCurrentJob.value ? trustedProgressStageKeys : cloneProgressStageKeys))
const trustedDisplayStageGroups = [
  { key: 'prepare', label: '准备', stageKeys: ['orchestrate', 'evidence_trace'] },
  { key: 'analysis', label: '分析', stageKeys: ['scope_index', 'scope_index_gate', 'requirement', 'requirement_gate'] },
  { key: 'generate', label: '生成', stageKeys: ['testcase_by_source_shard', 'testcase_gate'] },
  { key: 'review', label: '复核', stageKeys: ['quality_review'] },
  { key: 'delivery', label: '交付', stageKeys: ['export', 'final_delivery_gate'] }
]
const progressStageLabels = {
  orchestrate: '编排',
  collect: '收集',
  image_analysis: '识图',
  evidence_trace: '证据',
  scope_index: '索引',
  scope_index_gate: '范围门禁',
  requirement: '分析',
  requirement_gate: '需求门禁',
  testcase_by_source_shard: '用例基线',
  testcase: '设计',
  testcase_gate: '用例门禁',
  quality_review: '复核',
  review: '评审',
  export: '导出',
  final_delivery_gate: '交付门禁'
}
const progressStageItems = computed(() => {
  const stageMap = new Map(stageSummaries.value.map((item) => [item.key, item]))
  return progressStageKeys.value.map((key, index) => {
    const stage = stageMap.get(key)
    return {
      key,
      index: index + 1,
      label: progressStageLabels[key],
      status: stage?.status || 'pending',
      summary: stage?.summary || '',
      durationText: formatStageDuration(stage)
    }
  })
})
const displayProgressStageItems = computed(() => {
  if (!isTrustedCurrentJob.value) return progressStageItems.value
  const stageMap = new Map(stageSummaries.value.map((item) => [item.key, item]))
  return trustedDisplayStageGroups.map((group, index) => {
    const stages = group.stageKeys.map((key) => stageMap.get(key)).filter(Boolean)
    const failed = stages.find((item) => item.status === 'failed')
    const running = stages.find((item) => item.status === 'running')
    const hasAny = stages.length > 0
    const allSuccess = group.stageKeys.every((key) => stageMap.get(key)?.status === 'success')
    const lastFinished = stages
      .filter((item) => item?.updated_at)
      .slice()
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
    const activeStage = failed || running || lastFinished || stages[0]
    return {
      key: group.key,
      index: index + 1,
      label: group.label,
      status: failed ? 'failed' : (running ? 'running' : (allSuccess ? 'success' : (hasAny ? 'running' : 'pending'))),
      summary: activeStage?.summary || '',
      durationText: formatDisplayStageDuration(stages),
      childLabels: group.stageKeys.map((key) => progressStageLabels[key]).filter(Boolean).join(' / ')
    }
  })
})
const progressPercent = computed(() => {
  if (!currentJob.value) return 0
  if (['SUCCESS', 'CONDITIONAL'].includes(currentJob.value.status)) return 100
  const displayItems = displayProgressStageItems.value
  const completedCount = displayItems.filter((item) => item.status === 'success').length
  const runningIndex = displayItems.findIndex((item) => item.status === 'running')
  const failedIndex = displayItems.findIndex((item) => item.status === 'failed')
  const baseIndex = failedIndex >= 0 ? failedIndex : runningIndex
  const inProgressWeight = baseIndex >= 0 ? 0.45 : 0
  const raw = ((completedCount + inProgressWeight) / displayItems.length) * 100
  return Math.min(99, Math.max(0, Math.round(raw)))
})
const progressStatusText = computed(() => {
  if (!currentJob.value) return '请选择任务查看执行状态'
  if (currentJob.value.status === 'SUCCESS') return '全部阶段已完成'
  if (currentJob.value.status === 'CONDITIONAL') return '全部阶段已完成，结果需按风险项复核'
  if (currentJob.value.status === 'FAILED') return '任务执行失败，请查看错误摘要'
  if (currentJob.value.status === 'CANCELLED') return '任务已停止'
  const runningStage = displayProgressStageItems.value.find((item) => item.status === 'running')
  return runningStage ? `当前阶段：${runningStage.label}` : '等待任务调度'
})
const activeExecutionProof = computed(() => {
  if (!currentJob.value || !['RUNNING', 'PENDING'].includes(currentJob.value.status)) return ''
  const parts = []
  const latest = latestStageActivity.value
  if (latest?.updated_at) {
    parts.push(`最近活动 ${formatDateTime(latest.updated_at)}`)
  }
  if (latest?.summary) {
    parts.push(latest.summary)
  }
  if (currentJob.value.task_id) {
    parts.push(`task ${shortTaskId(currentJob.value.task_id)}`)
  }
  if (activeAttempt.value?.heartbeat_at) {
    parts.push(`心跳 ${formatDateTime(activeAttempt.value.heartbeat_at)}`)
  }
  return parts.join(' · ')
})

let pollTimer = null
let pollInFlight = false
let pollDelay = 3000
let pollCycle = 0

function extractRawUrl(value) {
  const raw = (value || '').trim()
  const match = raw.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/)
  return match ? match[2].trim() : raw
}

function isQwenModel(model) {
  return (model || '').toLowerCase().startsWith('qwen')
}

function isCodingPlanKey(apiKey) {
  return (apiKey || '').trim().startsWith('sk-sp-')
}

function normalizeApiKey(value) {
  let apiKey = (value || '').trim()
  while (apiKey.length >= 2 && ['"', "'"].includes(apiKey[0]) && apiKey.at(-1) === apiKey[0]) {
    apiKey = apiKey.slice(1, -1).trim()
  }
  return apiKey.replace(/^['"]+|['"]+$/g, '').trim()
}

function normalizeModelConfigInput() {
  const model = (modelConfig.value.model || '').trim()
  const apiKey = normalizeApiKey(modelConfig.value.api_key)
  const baseUrl = extractRawUrl(modelConfig.value.base_url)
  const matched = modelOptions.value.find((item) => item.value === model)
  let normalizedBaseUrl = baseUrl || matched?.baseUrl || ''

  if (isQwenModel(model)) {
    if (isCodingPlanKey(apiKey)) {
      normalizedBaseUrl = normalizedBaseUrl.includes('coding-intl.dashscope.aliyuncs.com')
        ? 'https://coding-intl.dashscope.aliyuncs.com/v1'
        : 'https://coding.dashscope.aliyuncs.com/v1'
    } else if (!normalizedBaseUrl || normalizedBaseUrl.includes('coding.dashscope.aliyuncs.com')) {
      normalizedBaseUrl = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    }
  }

  return { model, apiKey, baseUrl: normalizedBaseUrl }
}

function resolveModelProvider(model) {
  return modelOptions.value.find((item) => item.value === model)?.provider || 'OPENAI'
}

function validateModelConfigInput() {
  const { model, apiKey, baseUrl } = normalizeModelConfigInput()
  if (!apiKey) {
    return { model, apiKey, baseUrl }
  }
  if (isQwenModel(model)) {
    if (isCodingPlanKey(apiKey)) {
      if (!baseUrl.includes('coding.dashscope.aliyuncs.com/v1') && !baseUrl.includes('coding-intl.dashscope.aliyuncs.com/v1')) {
        throw new Error('sk-sp- 开头的阿里云 Coding Plan Key 必须配合 coding.dashscope.aliyuncs.com/v1 使用')
      }
    } else if (!baseUrl.includes('/compatible-mode/v1')) {
      throw new Error('Qwen 通用 API Key 需要配合 dashscope 的 compatible-mode/v1 地址使用')
    }
  } else if (isCodingPlanKey(apiKey)) {
    throw new Error('sk-sp- 开头的阿里云 Coding Plan Key 仅支持 Qwen 模型')
  }
  return { model, apiKey, baseUrl }
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  stopPolling()
  pollDelay = 3000
  pollCycle = 0
  scheduleNextPoll()
}

function scheduleNextPoll() {
  stopPolling()
  pollTimer = setTimeout(async () => {
    if (pollInFlight) return
    if (!currentJob.value) return
    if (!['RUNNING', 'PENDING'].includes(currentJob.value.status)) {
      stopPolling()
      return
    }
    pollInFlight = true
    try {
      await refreshCurrentJob({ refreshList: pollCycle % 4 === 3 })
      pollCycle += 1
      pollDelay = nextPollingDelay(pollDelay)
    } catch {
      pollDelay = nextPollingDelay(pollDelay, true)
    } finally {
      pollInFlight = false
      if (['RUNNING', 'PENDING'].includes(currentJob.value?.status)) {
        scheduleNextPoll()
      }
    }
  }, pollDelay)
}

watch(
  () => currentJob.value?.id,
  () => {
    activeArtifactType.value = visibleArtifacts.value[0]?.artifact_type || ''
  }
)

watch(
  () => activeArtifactType.value,
  async () => {
    if (activeArtifact.value && !activeArtifact.value.content_json && activeArtifact.value.artifact_type !== 'xmind') {
      await loadArtifactContent(activeArtifact.value)
    }
  }
)

watch(
  () => modelConfig.value.model,
  (model) => {
    const matched = modelOptions.value.find((item) => item.value === model)
    if (matched && matched.baseUrl) {
      modelConfig.value.base_url = matched.baseUrl
    }
    if (matched && matched.value === 'custom-openai-compatible' && !modelConfig.value.base_url) {
      modelConfig.value.base_url = ''
    }
  }
)

watch(
  () => currentJob.value?.status,
  (status) => {
    if (!status) {
      stopPolling()
      return
    }
    if (['RUNNING', 'PENDING'].includes(status)) {
      startPolling()
      return
    }
    stopPolling()
  },
  { immediate: true }
)

watch(
  () => form.value.project_id,
  async (projectId) => {
    if (!projectId) return
    await loadModelConfig()
    await fetchJobs()
  }
)

async function fetchProjects() {
  try {
    projects.value = await api.get('/projects')
    pageError.value = ''
    if (!form.value.project_id && projects.value.length) {
      form.value.project_id = projects.value[0].id
    }
    await loadModelConfig()
  } catch (error) {
    pageError.value = error?.message || '加载项目失败'
    ElMessage.error(pageError.value)
  }
}

async function fetchJobs() {
  try {
    const [projectJobs, visibleJobs] = await Promise.all([
      listCaseGenerationV2Jobs({
        projectId: form.value.project_id,
        status: jobStatusFilter.value,
        pipelineMode: jobModeFilter.value,
        limit: 50
      }),
      listCaseGenerationV2Jobs()
    ])
    jobs.value = projectJobs
    jobsHasMore.value = projectJobs.length === 50
    allJobs.value = visibleJobs
    pageError.value = ''
    if (!jobs.value.length) {
      currentJob.value = null
      currentArtifacts.value = []
      return
    }
    if (!currentJob.value) {
      await selectJob(pinnedRunningJob.value || jobs.value[0])
      return
    }
    const matched = jobs.value.find((item) => item.id === currentJob.value.id)
    if (!matched) {
      await selectJob(pinnedRunningJob.value || jobs.value[0])
    }
  } catch (error) {
    pageError.value = error?.message || '加载任务失败'
    throw error
  }
}

async function loadMoreJobs() {
  const beforeId = jobs.value.at(-1)?.id
  if (!beforeId || loadingMoreJobs.value) return
  loadingMoreJobs.value = true
  try {
    const older = await listCaseGenerationV2Jobs({
      projectId: form.value.project_id,
      status: jobStatusFilter.value,
      pipelineMode: jobModeFilter.value,
      beforeId,
      limit: 50
    })
    const existingIds = new Set(jobs.value.map((item) => item.id))
    jobs.value.push(...older.filter((item) => !existingIds.has(item.id)))
    jobsHasMore.value = older.length === 50
  } catch (error) {
    ElMessage.error(error?.message || '加载更多任务失败')
  } finally {
    loadingMoreJobs.value = false
  }
}

async function loadArtifactContent(artifact) {
  if (!currentJob.value || !artifact || artifact.content_json || artifact.artifact_type === 'xmind') return
  artifactLoading.value = true
  try {
    const hydrated = await getCaseGenerationV2Artifact(currentJob.value.id, artifact.id)
    currentArtifacts.value = currentArtifacts.value.map((item) => item.id === hydrated.id ? hydrated : item)
  } finally {
    artifactLoading.value = false
  }
}

async function hydrateSummaryArtifacts() {
  const summaryTypes = new Set([
    'trusted_review_report',
    'scope_index',
    'evidence_trace_gate',
    'scope_index_gate',
    'requirement_handoff',
    'testcase_handoff',
    'final_delivery_gate',
    'generation_metrics'
  ])
  const pending = currentArtifacts.value.filter((item) => summaryTypes.has(item.artifact_type) && !item.content_json)
  await Promise.all(pending.map((item) => loadArtifactContent(item)))
}

async function selectJob(job, options = {}) {
  try {
    const detail = await getCaseGenerationV2JobDetail(job.id)
    const previousContent = new Map(currentArtifacts.value.map((item) => [item.id, item.content_json]))
    currentJob.value = detail.job
    metricsComparison.value = null
    currentAttempts.value = detail.attempts || []
    currentArtifacts.value = (detail.artifacts || []).map((item) => ({
      ...item,
      content_json: previousContent.get(item.id) || item.content_json || null
    }))
    activeArtifactType.value = visibleArtifacts.value[0]?.artifact_type || ''
    if (options.hydrate !== false && !['RUNNING', 'PENDING'].includes(currentJob.value.status)) {
      await hydrateSummaryArtifacts()
    }
    if (!['RUNNING', 'PENDING'].includes(currentJob.value.status)) {
      try {
        metricsComparison.value = await getCaseGenerationV2MetricsComparison(currentJob.value.id)
      } catch {
        metricsComparison.value = null
      }
    }
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.message || '加载任务详情失败'
    ElMessage.error(pageError.value)
  }
}

async function refreshCurrentJob(options = {}) {
  if (!currentJob.value) return
  const wasRunning = ['RUNNING', 'PENDING'].includes(currentJob.value.status)
  await selectJob(currentJob.value, { hydrate: false })
  const index = jobs.value.findIndex((item) => item.id === currentJob.value.id)
  if (index >= 0) jobs.value.splice(index, 1, currentJob.value)
  const allIndex = allJobs.value.findIndex((item) => item.id === currentJob.value.id)
  if (allIndex >= 0) allJobs.value.splice(allIndex, 1, currentJob.value)
  const finished = wasRunning && !['RUNNING', 'PENDING'].includes(currentJob.value.status)
  if (finished) {
    await hydrateSummaryArtifacts()
  }
  if (options.refreshList || finished) {
    await fetchJobs()
  }
}

function currentWorkspaceId() {
  const project = projects.value.find((item) => item.id === form.value.project_id)
  return project?.workspace_id || currentJob.value?.workspace_id || null
}

async function loadModelConfig() {
  const workspaceId = currentWorkspaceId()
  if (!workspaceId) return
  const config = await getCaseGenerationV2ModelConfig(workspaceId)
  if (!config) {
    hasSavedModelConfig.value = false
    return
  }
  hasSavedModelConfig.value = true
  modelConfig.value = {
    name: config.name || '默认模型配置',
    api_key: '',
    model: config.model || 'gpt-5.5',
    base_url: config.base_url || ''
  }
}

async function loadModelOptions() {
  modelOptions.value = normalizeModelOptions(await listCaseGenerationV2ModelOptions())
}

async function persistModelConfig() {
  const workspaceId = currentWorkspaceId()
  if (!workspaceId) {
    throw new Error('请先选择所属项目')
  }
  const { model, apiKey, baseUrl } = validateModelConfigInput()
  if (!apiKey) {
    throw new Error('请填写模型 API Key')
  }
  await saveCaseGenerationV2ModelConfig({
    workspace_id: workspaceId,
    provider: resolveModelProvider(model),
    name: modelConfig.value.name || '默认模型配置',
    api_key: apiKey,
    model,
    base_url: baseUrl || null
  })
  hasSavedModelConfig.value = true
  modelConfig.value.model = model
  modelConfig.value.base_url = baseUrl
  modelConfig.value.api_key = ''
}

async function saveModelConfig() {
  savingModelConfig.value = true
  try {
    await persistModelConfig()
    ElMessage.success('模型配置已保存')
  } catch (error) {
    ElMessage.error(error?.message || '保存模型配置失败')
  } finally {
    savingModelConfig.value = false
  }
}

async function submitJob() {
  if (activeOwnJob.value) {
    ElMessage.error(`当前已有进行中的任务 #${activeOwnJob.value.id}`)
    return
  }
  if (!form.value.project_id || !form.value.name.trim()) {
    ElMessage.error('请先填写项目和任务名称')
    return
  }
  const sourceType = form.value.source_type
  const markdownText = (form.value.markdown_text || '').trim()
  const sourceUrl = (form.value.source_url || '').trim()
  if (sourceType === 'LINK' && !sourceUrl) {
    ElMessage.error('请填写需求文档链接')
    return
  }
  if (sourceType !== 'LINK' && markdownText.length < 10) {
    ElMessage.error(sourceType === 'UPLOAD' ? '请先上传需求文档' : '请先填写需求 Markdown')
    return
  }
  submitting.value = true
  try {
    if ((modelConfig.value.api_key || '').trim()) {
      await persistModelConfig()
    } else if (!hasSavedModelConfig.value) {
      ElMessage.error('请先填写并保存模型配置，或在当前页输入 API Key 后直接开始生成')
      return
    }
    const job = await createCaseGenerationV2Job({
      ...form.value,
      name: form.value.name.trim(),
      source_url: sourceUrl || null,
      markdown_text: sourceType === 'LINK' ? null : markdownText,
      ...normalizeModelConfigInput()
    })
    ElMessage.success('生成任务已提交')
    await fetchJobs()
    await selectJob(job)
  } catch (error) {
    ElMessage.error(error?.message || '创建任务失败')
  } finally {
    submitting.value = false
  }
}

function handleFileChange(uploadFile) {
  const rawFile = uploadFile.raw
  if (!rawFile) {
    return
  }
  const validationError = validateRequirementFile(rawFile)
  if (validationError) {
    ElMessage.error(validationError)
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const content = typeof reader.result === 'string' ? reader.result : ''
    form.value.markdown_text = content
    form.value.source_document_name = rawFile.name
    uploadedFileName.value = rawFile.name
    uploadedCharCount.value = content.length
    ElMessage.success('需求文档已读取')
  }
  reader.onerror = () => {
    ElMessage.error('读取文件失败')
  }
  reader.readAsText(rawFile, 'utf-8')
}

async function rerunJob() {
  if (!currentJob.value) return
  if (rerunDisabled.value) return
  if (activeOwnJob.value && activeOwnJob.value.id !== currentJob.value.id) {
    ElMessage.error(`当前已有进行中的任务 #${activeOwnJob.value.id}`)
    return
  }
  rerunning.value = true
  try {
    await rerunCaseGenerationV2Job(currentJob.value.id)
    ElMessage.success('任务已重新提交')
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || '重跑失败')
  } finally {
    rerunning.value = false
  }
}

async function rerunSourceShard(src) {
  if (!canRerunSourceShard(currentJob.value, isTrustedCurrentJob.value, src)) return
  if (activeOwnJob.value && activeOwnJob.value.id !== currentJob.value.id) {
    ElMessage.error(`当前已有进行中的任务 #${activeOwnJob.value.id}`)
    return
  }
  rerunningShard.value = src.source_id
  try {
    await rerunCaseGenerationV2SourceShard(currentJob.value.id, src.source_id)
    ElMessage.success(`${src.source_id} shard 已重新提交`)
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || 'source shard 重跑失败')
  } finally {
    rerunningShard.value = ''
  }
}

async function cancelJob() {
  if (!currentJob.value || cancelling.value) return
  cancelling.value = true
  try {
    const cancelledJob = await cancelCaseGenerationV2Job(currentJob.value.id)
    currentJob.value = cancelledJob
    ElMessage.success('任务已停止')
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || '停止失败')
  } finally {
    cancelling.value = false
  }
}

async function downloadArtifact(artifact) {
  if (!currentJob.value) return
  try {
    const blob = await downloadCaseGenerationV2Artifact(currentJob.value.id, artifact.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = artifact.file_name || `${artifact.artifact_type}.dat`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(error?.message || '下载失败')
  }
}

function shortTaskId(taskId) {
  const value = String(taskId || '')
  return value.length > 8 ? value.slice(0, 8) : value
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatStageDuration(stage) {
  if (!stage) return ''
  return formatDurationMs(stage.duration_ms)
}

function formatDisplayStageDuration(stages) {
  const total = (stages || []).reduce((sum, stage) => {
    const value = Number(stage?.duration_ms)
    return Number.isFinite(value) && value > 0 ? sum + value : sum
  }, 0)
  return formatDurationMs(total)
}

onMounted(async () => {
  if (!authStore.user && authStore.token) {
    await authStore.fetchProfile()
  }
  await loadModelOptions()
  await fetchProjects()
  await fetchJobs()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.case-generator-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.page-error-alert {
  margin-bottom: 12px;
}

.generator-layout {
  display: grid;
  grid-template-columns: minmax(280px, 2fr) minmax(280px, 2fr) minmax(360px, 3fr);
  gap: 18px;
  flex: 1;
  min-height: 0;
}

.generator-side {
  display: contents;
  min-width: 0;
}

@media (max-width: 1100px) {
  .generator-layout {
    grid-template-columns: 1fr;
    overflow: auto;
    padding-right: 4px;
  }

  .generator-side {
    display: grid;
    grid-template-rows: auto;
    gap: 18px;
  }
}

@media (max-width: 768px) {
  .generator-side {
    grid-template-columns: 1fr;
  }
}
</style>
