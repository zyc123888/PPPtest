<template>
  <el-card class="page-card generator-composer" shadow="never">
    <div class="panel-head">
      <div class="panel-title">生成输入</div>
      <el-tag type="success">V2 claw_5skill_unified</el-tag>
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
      <el-form-item label="生成模式">
        <el-radio-group v-model="form.pipeline_mode" class="pipeline-mode-group">
          <el-radio-button v-for="item in pipelineModeOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </el-radio-button>
        </el-radio-group>
        <div class="pipeline-mode-hint">{{ selectedPipelineModeHint }}</div>
      </el-form-item>
      <el-form-item v-if="form.pipeline_mode === 'trusted'" label="可信生成策略">
        <el-radio-group v-model="form.trusted_generation_strategy" class="pipeline-mode-group">
          <el-radio-button value="source_shard">按 source 分片</el-radio-button>
          <el-radio-button value="lite_review">轻量结果审查</el-radio-button>
        </el-radio-group>
        <div class="pipeline-mode-hint">
          {{ form.trusted_generation_strategy === 'source_shard'
            ? '每个 source 独立生成并保留用例追踪证据。'
            : '复用轻量结果后执行可信结构审查，仅适合作为快速预览。' }}
        </div>
      </el-form-item>
      <el-form-item
        v-if="form.pipeline_mode === 'trusted' && form.trusted_generation_strategy === 'source_shard'"
        label="生成密度"
      >
        <el-radio-group v-model="form.generation_density" class="pipeline-mode-group generation-density-group">
          <el-radio-button v-for="item in generationDensityOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </el-radio-button>
        </el-radio-group>
        <div class="pipeline-mode-hint">{{ selectedGenerationDensityHint }}</div>
      </el-form-item>
      <el-form-item label="模型配置">
        <div class="model-config-panel">
          <el-input v-model="modelConfig.name" placeholder="配置名称，例如：默认 GPT 配置" />
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
        <el-select
          v-model="modelConfig.model"
          class="model-select"
          placeholder="请选择或输入模型"
          filterable
          allow-create
          default-first-option
        >
          <el-option-group v-for="group in groupedModelOptions" :key="group.label" :label="group.label">
            <el-option v-for="item in group.options" :key="item.value" :label="item.label" :value="item.value" />
          </el-option-group>
        </el-select>
        <el-input v-model="modelConfig.base_url" placeholder="可选：自定义 OpenAI 兼容 base_url；不填则使用预设" />
        <div class="model-config-actions">
          <el-button size="small" @click="emit('load-model-config')">读取已保存配置</el-button>
          <el-button size="small" type="primary" :loading="savingModelConfig" @click="emit('save-model-config')">保存模型配置</el-button>
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
            :on-change="(file) => emit('file-change', file)"
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
        <el-input v-model="form.source_url" placeholder="例如：https://docs.example.com/prd/login-center 或 raw markdown 链接" />
      </el-form-item>
      <div class="form-footer">
        <el-checkbox v-model="form.export_xmind" disabled>同时导出 XMind</el-checkbox>
        <el-tag type="info">默认开启</el-tag>
      </div>
    </el-form>
  </el-card>
</template>

<script setup>
import { computed } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'

const form = defineModel('form', { type: Object, required: true })
const modelConfig = defineModel('modelConfig', { type: Object, required: true })

defineProps({
  projects: { type: Array, default: () => [] },
  groupedModelOptions: { type: Array, default: () => [] },
  savingModelConfig: { type: Boolean, default: false },
  uploadedFileName: { type: String, default: '' },
  uploadedCharCount: { type: Number, default: 0 }
})

const emit = defineEmits(['load-model-config', 'save-model-config', 'file-change'])

const pipelineModeOptions = [
  { label: '轻量模式', value: 'lite', hint: '轻量适用性判断，生成 XMind。' },
  { label: '可信模式', value: 'trusted', hint: '先建立范围索引，再按 source 追溯、适用方法和 must_cover 生成可解释用例。' }
]

const generationDensityOptions = [
  { label: '精简', value: 'concise', hint: '聚焦核心主流程和高风险点，允许低风险同构场景合并。' },
  { label: '均衡', value: 'balanced', hint: '覆盖核心、边界与关键异常，按风险控制合并。' },
  { label: '全面', value: 'exhaustive', hint: '展开权限、状态、组合和异常，仅合并完全重复场景。' }
]

const selectedPipelineModeHint = computed(() =>
  pipelineModeOptions.find((item) => item.value === form.value.pipeline_mode)?.hint || ''
)

const selectedGenerationDensityHint = computed(() =>
  generationDensityOptions.find((item) => item.value === form.value.generation_density)?.hint || ''
)
</script>

<style scoped>
.generator-composer {
  border-radius: 20px;
  height: 100%;
  min-height: 0;
}

.generator-composer :deep(.el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
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

.composer-form {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.generator-composer :deep(.el-form-item) {
  margin-bottom: 14px;
}

.generator-composer :deep(.el-textarea__inner) {
  min-height: 138px !important;
}

.pipeline-mode-group {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.pipeline-mode-group :deep(.el-radio-button) {
  min-width: 0;
}

.pipeline-mode-group :deep(.el-radio-button__inner) {
  width: 100%;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
}

.generation-density-group {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.pipeline-mode-hint {
  margin-top: 8px;
  width: 100%;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.model-config-panel,
.model-config-actions {
  display: grid;
  gap: 10px;
  width: 100%;
}

.model-config-actions {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.model-select {
  width: 100%;
}

.source-type-group {
  width: 100%;
  display: flex;
  flex-wrap: nowrap;
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

.upload-panel {
  display: grid;
  gap: 12px;
  width: 100%;
}

.upload-result,
.form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.upload-result__meta {
  color: var(--color-text-secondary);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .generator-composer {
    height: min(760px, calc(100vh - 150px));
    min-height: 620px;
  }
}

@media (max-width: 768px) {
  .form-footer,
  .panel-head {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
