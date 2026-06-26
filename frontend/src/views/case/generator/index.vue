<template>
  <div class="app-page case-generator-page">
    <PageHeader title="用例生成" subtitle="把需求 Markdown 收口为证据链、功能点、测试包和 XMind 初稿。">
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
      <el-card class="page-card generator-composer" shadow="never">
        <div class="panel-head">
          <div>
            <div class="panel-title">生成输入</div>
          </div>
          <el-tag type="success">claw_5skill_final XMind</el-tag>
        </div>

        <el-form class="composer-form" label-position="top" :model="form">
          <el-form-item label="所属项目" required>
            <el-select v-model="form.project_id" placeholder="请选择项目" filterable>
              <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="任务名称" required>
            <el-input v-model="form.name" placeholder="例如：支付中心 PRD 初版用例生成" />
          </el-form-item>
          <el-form-item label="模型配置">
            <div class="model-config-panel">
              <el-input
                v-model="modelConfig.name"
                placeholder="配置名称，例如：默认 GPT 配置"
              />
              <el-input
                v-model="modelConfig.api_key"
                type="password"
                show-password
                autocomplete="off"
                placeholder="工作空间级 API Key，保存后供新建和重跑任务复用"
              />
            </div>
          </el-form-item>
          <el-form-item label="模型">
            <el-select v-model="modelConfig.model" class="model-select" placeholder="请选择模型">
              <el-option-group
                v-for="group in groupedModelOptions"
                :key="group.label"
                :label="group.label"
              >
                <el-option
                  v-for="item in group.options"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-option-group>
            </el-select>
            <el-input
              v-model="modelConfig.base_url"
              placeholder="可选：自定义 OpenAI 兼容 base_url；不填则使用预设"
            />
            <div class="model-config-actions">
              <el-button size="small" @click="loadModelConfig">读取已保存配置</el-button>
              <el-button size="small" type="primary" :loading="savingModelConfig" @click="saveModelConfig">保存模型配置</el-button>
            </div>
          </el-form-item>
          <el-form-item label="需求来源">
            <el-radio-group v-model="form.source_type" class="source-type-group">
              <el-radio-button label="PASTE">粘贴文本</el-radio-button>
              <el-radio-button label="UPLOAD">上传文档</el-radio-button>
              <el-radio-button label="LINK">需求链接</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="form.source_type === 'PASTE'" label="需求 Markdown" required>
            <el-input
              v-model="form.markdown_text"
              type="textarea"
              :rows="7"
              placeholder="# 登录模块&#10;- 支持用户名密码登录&#10;- 首次登录需要验证码&#10;&#10;# 权限管理&#10;- 不同角色显示不同菜单"
            />
          </el-form-item>
          <el-form-item v-else-if="form.source_type === 'UPLOAD'" label="上传需求文档" required>
            <div class="upload-panel">
              <el-upload
                class="generator-upload"
                drag
                :auto-upload="false"
                :show-file-list="false"
                accept=".md,.markdown,.txt"
                action="#"
                :on-change="handleFileChange"
              >
                <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
                <div class="el-upload__text">拖拽文件到这里，或 <em>点击选择 .md / .txt</em></div>
                <template #tip>
                  <div class="el-upload__tip">文件不会直接上传到服务器，会先在浏览器中读取内容再提交生成任务。</div>
                </template>
              </el-upload>
              <div v-if="uploadedFileName" class="upload-result">
                <el-tag type="success">{{ uploadedFileName }}</el-tag>
                <span class="upload-result__meta">{{ uploadedCharCount }} 字</span>
              </div>
              <el-input
                v-model="form.markdown_text"
                type="textarea"
                :rows="7"
                readonly
                placeholder="读取后的文件内容会显示在这里"
              />
            </div>
          </el-form-item>
          <el-form-item v-else label="需求文档链接" required>
            <el-input
              v-model="form.source_url"
              placeholder="例如：https://docs.example.com/prd/login-center 或 raw markdown 链接"
            />
          </el-form-item>
          <div class="form-footer">
            <el-checkbox v-model="form.export_xmind" disabled>同时导出 XMind</el-checkbox>
            <el-tag type="info">默认开启</el-tag>
          </div>
        </el-form>
      </el-card>

      <div class="generator-side">
        <el-card class="page-card side-card" shadow="never">
          <div class="panel-head">
            <div>
              <div class="panel-title">最近任务</div>
            </div>
          </div>
          <div class="job-list">
            <div v-if="pinnedRunningJob" class="job-pinned">
              <div class="job-pinned__label">进行中</div>
              <div
                class="job-item job-item--pinned"
                :class="{ active: currentJob?.id === pinnedRunningJob.id }"
                role="button"
                tabindex="0"
                @click="selectJob(pinnedRunningJob)"
                @keydown.enter.prevent="selectJob(pinnedRunningJob)"
                @keydown.space.prevent="selectJob(pinnedRunningJob)"
              >
                <div class="job-item__title">{{ pinnedRunningJob.name }}</div>
                <div class="job-item__meta">
                  <span>#{{ pinnedRunningJob.id }}</span>
                  <el-tag size="small" :type="statusTagType(pinnedRunningJob.status)">{{ pinnedRunningJob.status }}</el-tag>
                </div>
                <div class="job-item__desc">{{ pinnedRunningJob.summary || '暂无摘要' }}</div>
              </div>
            </div>

            <div
              v-for="item in jobList"
              :key="item.id"
              class="job-item"
              :class="{ active: currentJob?.id === item.id }"
              role="button"
              tabindex="0"
              @click="selectJob(item)"
              @keydown.enter.prevent="selectJob(item)"
              @keydown.space.prevent="selectJob(item)"
            >
              <div class="job-item__title">{{ item.name }}</div>
              <div class="job-item__meta">
                <span>#{{ item.id }}</span>
                <el-tag size="small" :type="statusTagType(item.status)">{{ item.status }}</el-tag>
              </div>
              <div class="job-item__desc">{{ item.summary || '暂无摘要' }}</div>
            </div>
            <el-empty v-if="!jobs.length" description="暂无生成任务" />
          </div>
        </el-card>

        <el-card class="page-card side-card" shadow="never">
          <div class="panel-head">
            <div>
              <div class="panel-title">结果详情</div>
            </div>
            <div class="detail-actions">
              <div class="detail-actions__primary">
                <el-button v-if="canRerunCurrentJob" size="small" :loading="rerunning" :disabled="rerunDisabled" @click="rerunJob">重跑</el-button>
                <el-button v-if="canCancelCurrentJob" size="small" type="danger" plain @click="cancelJob">停止任务</el-button>
              </div>
              <el-button v-if="currentJob" size="small" class="detail-actions__secondary" @click="refreshCurrentJob">刷新详情</el-button>
            </div>
          </div>

          <el-empty v-if="!currentJob" description="请选择一个任务查看详情" />

          <template v-else>
            <div class="detail-summary">
              <div class="summary-line"><span>状态</span><el-tag :type="statusTagType(currentJob.status)">{{ currentJob.status }}</el-tag></div>
              <div class="summary-line"><span>摘要</span><strong>{{ currentJob.summary || '-' }}</strong></div>
              <div class="summary-line"><span>来源</span><span>{{ currentJob.source_document_name || '-' }}</span></div>
              <div class="summary-line" v-if="currentJob.error_message"><span>错误</span><span class="error-text">{{ currentJob.error_message }}</span></div>
            </div>

            <div class="progress-card">
              <div class="progress-card__head">
                <div>
                  <div class="progress-card__title">执行进度</div>
                  <div class="progress-card__subtitle">{{ progressStatusText }}</div>
                </div>
                <div class="progress-percent">{{ progressPercent }}%</div>
              </div>
              <div class="progress-track" aria-hidden="true">
                <div class="progress-track__fill" :style="{ width: `${progressPercent}%` }"></div>
              </div>
              <div class="progress-stage-rail">
                <div
                  v-for="stage in progressStageItems"
                  :key="stage.key"
                  class="progress-stage-node"
                  :class="`is-${stage.status}`"
                >
                  <div class="progress-stage-node__dot">{{ stage.index }}</div>
                  <div class="progress-stage-node__label">{{ stage.label }}</div>
                  <div v-if="stage.durationText" class="progress-stage-node__duration">{{ stage.durationText }}</div>
                </div>
              </div>
              <div class="stage-summary-list">
                <div
                  v-for="stage in stageSummaries"
                  :key="stage.key"
                  class="stage-summary-item"
                  :class="`is-${stage.status || 'pending'}`"
                >
                  <div class="stage-summary-item__title-wrap">
                    <div class="stage-summary-item__title">{{ stage.title }}</div>
                    <div v-if="formatStageDuration(stage)" class="stage-summary-item__duration">{{ formatStageDuration(stage) }}</div>
                  </div>
                  <el-tag size="small" :type="stageTagType(stage.status)">{{ stage.status }}</el-tag>
                  <div class="stage-summary-item__desc">{{ stage.summary || '-' }}</div>
                </div>
              </div>
            </div>

            <div v-if="finalXmindArtifact" class="xmind-download-card">
              <div>
                <div class="xmind-download-card__title">最终 XMind 用例</div>
                <div class="xmind-download-card__desc">{{ finalXmindArtifact.file_name }}</div>
              </div>
              <el-button type="primary" @click="downloadArtifact(finalXmindArtifact)">下载 .xmind</el-button>
            </div>
            <el-alert
              v-else-if="currentJob.status === 'SUCCESS'"
              title="当前任务未找到 .xmind 产物"
              type="warning"
              :closable="false"
            />
            <el-alert
              v-if="exportLogArtifact"
              :title="formatArtifactContent(exportLogArtifact)"
              type="error"
              :closable="false"
              class="export-log-alert"
            />
          </template>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import {
  cancelCaseGenerationJob,
  caseGenerationArtifactLabel,
  caseGenerationStatusTagType,
  createCaseGenerationJob,
  getCaseGenerationModelConfig,
  downloadCaseGenerationArtifact,
  formatCaseGenerationArtifactContent,
  getCaseGenerationJobDetail,
  listCaseGenerationJobs,
  rerunCaseGenerationJob,
  saveCaseGenerationModelConfig
} from '@/lib/caseGeneration'

const projects = ref([])
const jobs = ref([])
const allJobs = ref([])
const currentJob = ref(null)
const currentArtifacts = ref([])
const activeArtifactType = ref('')
const submitting = ref(false)
const rerunning = ref(false)
const savingModelConfig = ref(false)
const hasSavedModelConfig = ref(false)
const authStore = useAuthStore()

const form = ref({
  project_id: null,
  name: '',
  mode: 'MARKDOWN',
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

const modelOptions = [
  { provider: 'OpenAI', label: 'GPT-5.5', value: 'gpt-5.5', baseUrl: 'https://api.openai.com/v1' },
  { provider: 'OpenAI', label: 'GPT-5.4', value: 'gpt-5.4', baseUrl: 'https://api.openai.com/v1' },
  { provider: 'Ollama', label: 'gpt-oss:120b', value: 'gpt-oss:120b', baseUrl: 'https://ollama.com/v1' },
  { provider: 'Ollama', label: 'glm-5.1', value: 'glm-5.1', baseUrl: 'https://ollama.com/v1' },
  { provider: 'Ollama', label: 'kimi-k2.6', value: 'kimi-k2.6', baseUrl: 'https://ollama.com/v1' },
  { provider: 'Ollama', label: 'minimax-m3', value: 'minimax-m3', baseUrl: 'https://ollama.com/v1' },
  { provider: 'Ollama', label: 'qwen3.5', value: 'qwen3.5', baseUrl: 'https://ollama.com/v1' },
  { provider: 'Qwen', label: 'qwen3.7-plus', value: 'qwen3.7-plus', baseUrl: 'https://coding.dashscope.aliyuncs.com/v1' },
  { provider: 'Qwen', label: 'qwen3.6-plus', value: 'qwen3.6-plus', baseUrl: 'https://coding.dashscope.aliyuncs.com/v1' },
  { provider: 'Qwen', label: 'qwen3.5-plus', value: 'qwen3.5-plus', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { provider: 'Qwen', label: 'qwen-max', value: 'qwen-max', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { provider: 'DeepSeek', label: 'deepseek-chat', value: 'deepseek-chat', baseUrl: 'https://api.deepseek.com/v1' },
  { provider: 'DeepSeek', label: 'deepseek-reasoner', value: 'deepseek-reasoner', baseUrl: 'https://api.deepseek.com/v1' },
  { provider: 'GLM', label: 'glm-4.5', value: 'glm-4.5', baseUrl: 'https://open.bigmodel.cn/api/paas/v4' },
  { provider: 'GLM', label: 'glm-4.5-air', value: 'glm-4.5-air', baseUrl: 'https://open.bigmodel.cn/api/paas/v4' },
  { provider: 'Custom', label: '自定义 OpenAI 兼容模型', value: 'custom-openai-compatible', baseUrl: '' }
]
const groupedModelOptions = computed(() => {
  const groups = new Map()
  for (const item of modelOptions) {
    if (!groups.has(item.provider)) {
      groups.set(item.provider, [])
    }
    groups.get(item.provider).push(item)
  }
  return Array.from(groups.entries()).map(([label, options]) => ({ label, options }))
})

const visibleArtifacts = computed(() => currentArtifacts.value.filter((item) => item.artifact_type === 'xmind' || item.artifact_type === 'xmind_export_log'))
const finalXmindArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'xmind'))
const exportLogArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'xmind_export_log'))
const canRerunCurrentJob = computed(() => !!currentJob.value)
const rerunDisabled = computed(() => rerunning.value || !currentJob.value || ['RUNNING', 'PENDING'].includes(currentJob.value.status))
const selectedModelOption = computed(() => modelOptions.find((item) => item.value === modelConfig.value.model))
const currentUserId = computed(() => authStore.user?.id || null)

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
const progressStageKeys = ['collect', 'image_analysis', 'requirement', 'testcase', 'review', 'export']
const progressStageLabels = {
  collect: '收集',
  image_analysis: '识图',
  requirement: '分析',
  testcase: '设计',
  review: '评审',
  export: '导出'
}
const progressActiveIndex = computed(() => {
  if (!currentJob.value) return 0
  const stageMap = new Map(stageSummaries.value.map((item) => [item.key, item.status]))
  const index = progressStageKeys.findIndex((key) => stageMap.get(key) !== 'success')
  if (currentJob.value.status === 'SUCCESS') return progressStageKeys.length
  return index === -1 ? 0 : index
})
const progressStageItems = computed(() => {
  const stageMap = new Map(stageSummaries.value.map((item) => [item.key, item]))
  return progressStageKeys.map((key, index) => {
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
const progressPercent = computed(() => {
  if (!currentJob.value) return 0
  if (currentJob.value.status === 'SUCCESS') return 100
  const completedCount = progressStageItems.value.filter((item) => item.status === 'success').length
  const runningIndex = progressStageItems.value.findIndex((item) => item.status === 'running')
  const failedIndex = progressStageItems.value.findIndex((item) => item.status === 'failed')
  const baseIndex = failedIndex >= 0 ? failedIndex : runningIndex
  const inProgressWeight = baseIndex >= 0 ? 0.45 : 0
  const raw = ((completedCount + inProgressWeight) / progressStageKeys.length) * 100
  return Math.min(99, Math.max(0, Math.round(raw)))
})
const progressStatusText = computed(() => {
  if (!currentJob.value) return '请选择任务查看执行状态'
  if (currentJob.value.status === 'SUCCESS') return '全部阶段已完成'
  if (currentJob.value.status === 'FAILED') return '任务执行失败，请查看错误摘要'
  if (currentJob.value.status === 'CANCELLED') return '任务已停止'
  const runningStage = progressStageItems.value.find((item) => item.status === 'running')
  return runningStage ? `当前阶段：${runningStage.label}` : '等待任务调度'
})

let pollTimer = null
let pollInFlight = false

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
  const matched = modelOptions.find((item) => item.value === model)
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
  return modelOptions.find((item) => item.value === model)?.provider || 'OPENAI'
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
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (pollInFlight) return
    if (!currentJob.value) return
    if (!['RUNNING', 'PENDING'].includes(currentJob.value.status)) {
      stopPolling()
      return
    }
    pollInFlight = true
    try {
      await refreshCurrentJob()
    } finally {
      pollInFlight = false
    }
  }, 5000)
}

watch(
  () => currentJob.value?.id,
  () => {
    activeArtifactType.value = visibleArtifacts.value[0]?.artifact_type || ''
  }
)

watch(
  () => modelConfig.value.model,
  (model) => {
    const matched = modelOptions.find((item) => item.value === model)
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
      listCaseGenerationJobs({ projectId: form.value.project_id }),
      listCaseGenerationJobs()
    ])
    jobs.value = projectJobs
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
    jobs.value = []
    allJobs.value = []
    currentJob.value = null
    currentArtifacts.value = []
    pageError.value = error?.message || '加载任务失败'
    ElMessage.error(pageError.value)
  }
}

async function selectJob(job) {
  try {
    const detail = await getCaseGenerationJobDetail(job.id)
    currentJob.value = detail.job
    currentArtifacts.value = detail.artifacts || []
    activeArtifactType.value = currentArtifacts.value[0]?.artifact_type || ''
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.message || '加载任务详情失败'
    ElMessage.error(pageError.value)
  }
}

async function refreshCurrentJob() {
  if (!currentJob.value) return
  await selectJob(currentJob.value)
  await fetchJobs()
}

function currentWorkspaceId() {
  const project = projects.value.find((item) => item.id === form.value.project_id)
  return project?.workspace_id || currentJob.value?.workspace_id || null
}

async function loadModelConfig() {
  const workspaceId = currentWorkspaceId()
  if (!workspaceId) return
  const config = await getCaseGenerationModelConfig(workspaceId)
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

async function persistModelConfig() {
  const workspaceId = currentWorkspaceId()
  if (!workspaceId) {
    throw new Error('请先选择所属项目')
  }
  const { model, apiKey, baseUrl } = validateModelConfigInput()
  if (!apiKey) {
    throw new Error('请填写模型 API Key')
  }
  await saveCaseGenerationModelConfig({
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
    const job = await createCaseGenerationJob({
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
    await rerunCaseGenerationJob(currentJob.value.id)
    ElMessage.success('任务已重新提交')
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || '重跑失败')
  } finally {
    rerunning.value = false
  }
}

async function cancelJob() {
  if (!currentJob.value) return
  try {
    await cancelCaseGenerationJob(currentJob.value.id)
    ElMessage.success('任务已停止')
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || '停止失败')
  }
}

async function downloadArtifact(artifact) {
  if (!currentJob.value) return
  try {
    const blob = await downloadCaseGenerationArtifact(currentJob.value.id, artifact.id)
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

function statusTagType(status) {
  return caseGenerationStatusTagType(status)
}

function artifactLabel(artifact) {
  return caseGenerationArtifactLabel(artifact)
}

function formatArtifactContent(artifact) {
  return formatCaseGenerationArtifactContent(artifact)
}

function stageTagType(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function formatDurationMs(durationMs) {
  const value = Number(durationMs)
  if (!Number.isFinite(value) || value <= 0) return ''
  const totalSeconds = Math.max(1, Math.round(value / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes <= 0) return `${seconds}s`
  if (minutes < 60) return `${minutes}m ${seconds}s`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}h ${remainMinutes}m ${seconds}s`
}

function formatStageDuration(stage) {
  if (!stage) return ''
  return formatDurationMs(stage.duration_ms)
}

onMounted(async () => {
  if (!authStore.user && authStore.token) {
    await authStore.fetchProfile()
  }
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

.generator-layout {
  display: grid;
  grid-template-columns: minmax(280px, 2fr) minmax(280px, 2fr) minmax(360px, 3fr);
  gap: 18px;
  flex: 1;
  min-height: 0;
}

.generator-composer,
.side-card {
  border-radius: 20px;
  height: 100%;
  min-height: 0;
}

.generator-composer,
.generator-side {
  min-height: 0;
}

.generator-composer :deep(.el-card__body),
.side-card :deep(.el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.composer-form {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.generator-composer .panel-subtitle {
  max-width: 32ch;
}

.generator-composer :deep(.el-form-item) {
  margin-bottom: 14px;
}

.generator-composer :deep(.el-textarea__inner) {
  min-height: 138px !important;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.panel-title {
  font-size: 18px;
  font-weight: 700;
}

.panel-subtitle {
  margin-top: 6px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.model-config-panel,
.model-config-actions {
  display: grid;
  gap: 10px;
  width: 100%;
}

.model-config-panel {
  grid-template-columns: 1fr;
}

.model-config-actions {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.source-type-group {
  width: 100%;
  display: flex;
  flex-wrap: nowrap;
  gap: 0;
}

.source-type-group :deep(.el-radio-button) {
  flex: 1 1 0;
  min-width: 0;
  margin-left: -1px;
}

.source-type-group :deep(.el-radio-button:first-child) {
  margin-left: 0;
}

.source-type-group :deep(.el-radio-button__inner) {
  width: 100%;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
  border-radius: 0;
}

.source-type-group :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-radius: 12px 0 0 12px;
}

.source-type-group :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 0 12px 12px 0;
}

.source-type-group :deep(.el-radio-button:first-child:last-child .el-radio-button__inner) {
  border-radius: 10px;
}

.model-select {
  width: 100%;
}

.upload-panel {
  display: grid;
  gap: 12px;
  width: 100%;
}

.upload-result {
  display: flex;
  align-items: center;
  gap: 10px;
}

.upload-result__meta {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.generator-side {
  display: contents;
  min-width: 0;
}

.job-list {
  display: grid;
  gap: 12px;
  overflow: auto;
  min-height: 0;
}

.job-item {
  display: grid;
  align-content: start;
  grid-auto-rows: min-content;
  width: 100%;
  box-sizing: border-box;
  appearance: none;
  -webkit-appearance: none;
  font: inherit;
  color: inherit;
  line-height: inherit;
  text-align: left;
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 16px;
  padding: 12px 14px;
  background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(246,248,255,0.96));
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
  outline: none;
  min-height: 98px;
}

.job-item--pinned {
  border-color: rgba(79, 70, 229, 0.26);
  background: rgba(246, 248, 255, 0.92);
}

.job-pinned__label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(79, 70, 229, 0.72);
}

.job-item.active {
  border-color: rgba(79, 70, 229, 0.32);
  background: linear-gradient(180deg, rgba(244, 246, 255, 0.92), rgba(248, 250, 255, 0.98));
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.08);
  position: relative;
  overflow: hidden;
}

.job-item.active::before {
  content: '';
  position: absolute;
  top: 8px;
  right: 8px;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.job-item__title {
  font-weight: 700;
}

.job-item__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  color: var(--color-text-secondary);
}

.job-item__desc {
  margin-top: 8px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.detail-actions {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  margin-left: auto;
  flex-shrink: 0;
}

.detail-actions__primary {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  flex-wrap: nowrap;
}

.detail-actions__secondary {
  align-self: auto;
}

.detail-actions :deep(.el-button) {
  flex: 0 0 auto;
  white-space: nowrap;
  padding-inline: 10px;
}

.detail-summary {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(248, 250, 255, 0.88);
}

.stage-summary-list {
  display: grid;
  gap: 10px;
}

.stage-summary-item {
  display: grid;
  grid-template-columns: minmax(72px, 96px) auto;
  gap: 8px 12px;
  align-items: center;
  padding: 11px 13px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(255, 255, 255, 0.78);
}

.stage-summary-item.is-running {
  border-color: rgba(79, 70, 229, 0.24);
  background: linear-gradient(135deg, rgba(238, 242, 255, 0.92), rgba(255, 255, 255, 0.82));
}

.stage-summary-item.is-success {
  border-color: rgba(20, 184, 166, 0.2);
}

.stage-summary-item__title {
  font-weight: 600;
}

.stage-summary-item__title-wrap {
  display: grid;
  gap: 4px;
}

.stage-summary-item__duration {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.stage-summary-item__desc {
  grid-column: 1 / -1;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.export-log-alert {
  margin-top: 12px;
}

.progress-card {
  display: grid;
  gap: 14px;
  margin-bottom: 14px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(99, 102, 241, 0.14);
  background:
    radial-gradient(circle at 8% 0%, rgba(79, 70, 229, 0.1), transparent 32%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(246, 248, 255, 0.9));
  box-shadow: 0 18px 44px rgba(79, 70, 229, 0.08);
}

.progress-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.progress-card__title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.progress-card__subtitle {
  margin-top: 5px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.progress-percent {
  min-width: 58px;
  padding: 6px 10px;
  border-radius: 999px;
  text-align: center;
  font-weight: 800;
  color: #3730a3;
  background: rgba(238, 242, 255, 0.96);
  border: 1px solid rgba(99, 102, 241, 0.16);
}

.progress-track {
  position: relative;
  height: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.9);
}

.progress-track__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #4f46e5 52%, #14b8a6);
  box-shadow: 0 0 18px rgba(79, 70, 229, 0.28);
  transition: width 360ms ease;
}

.progress-stage-rail {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
}

.progress-stage-node {
  display: grid;
  justify-items: center;
  gap: 7px;
  min-width: 0;
  color: var(--color-text-secondary);
}

.progress-stage-node__dot {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(255, 255, 255, 0.88);
  font-size: 12px;
  font-weight: 800;
}

.progress-stage-node__label {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
}

.progress-stage-node__duration {
  font-size: 11px;
  line-height: 1;
  color: var(--color-text-secondary);
}

.progress-stage-node.is-success .progress-stage-node__dot {
  border-color: rgba(20, 184, 166, 0.22);
  color: #0f766e;
  background: linear-gradient(135deg, rgba(204, 251, 241, 0.96), rgba(240, 253, 250, 0.96));
}

.progress-stage-node.is-running .progress-stage-node__dot {
  border-color: rgba(79, 70, 229, 0.34);
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  box-shadow: 0 10px 22px rgba(79, 70, 229, 0.28);
}

.progress-stage-node.is-failed .progress-stage-node__dot {
  border-color: rgba(220, 38, 38, 0.22);
  color: #b91c1c;
  background: rgba(254, 226, 226, 0.94);
}

.summary-line {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.summary-line span:first-child {
  color: var(--color-text-secondary);
}

.xmind-download-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid rgba(22, 163, 74, 0.22);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(240, 253, 244, 0.96), rgba(236, 253, 245, 0.72));
}

.xmind-download-card__title {
  font-weight: 800;
  color: #166534;
}

.xmind-download-card__desc {
  margin-top: 6px;
  color: var(--color-text-secondary);
  word-break: break-all;
}

.artifact-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 10px;
}

.artifact-preview {
  margin: 0;
  padding: 14px;
  flex: 1;
  min-height: 240px;
  overflow: auto;
  border-radius: 16px;
  background: #0f172a;
  color: #dbeafe;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.error-text {
  color: #dc2626;
}

@media (max-width: 1100px) {
  .generator-layout {
    grid-template-columns: 1fr;
  }

  .generator-side {
    display: grid;
    gap: 18px;
    grid-template-rows: auto;
  }
}

@media (max-width: 768px) {
  .generator-side {
    display: grid;
    grid-template-columns: 1fr;
  }

  .progress-stage-rail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .form-footer,
  .xmind-download-card,
  .panel-head {
    flex-direction: column;
    align-items: stretch;
  }

  .detail-actions {
    justify-content: flex-start;
    margin-left: 0;
  }

  .detail-actions__primary,
  .detail-actions__secondary {
    align-self: auto;
  }

  .detail-actions__primary {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>
