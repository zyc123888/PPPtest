<template>
  <el-dialog
    :model-value="modelValue"
    class="ai-composer-dialog"
    width="min(920px, 94vw)"
    top="5vh"
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="composer-header">
        <span class="composer-header__icon"><el-icon><MagicStick /></el-icon></span>
        <div>
          <strong>AI 创建 UI 用例</strong>
          <span>{{ draftReady ? '检查生成步骤，确认后保存或直接试运行' : '描述测试目标，AI 将生成可执行步骤和断言' }}</span>
        </div>
        <el-tag effect="plain" type="success">ui-case-designer · v2.0.1</el-tag>
      </div>
    </template>

    <div class="composer-progress" aria-label="创建进度">
      <div class="composer-progress__item is-complete">
        <span><el-icon><EditPen /></el-icon></span>
        <div><strong>描述目标</strong><small>地址与测试意图</small></div>
      </div>
      <i :class="{ 'is-active': draftReady }" />
      <div class="composer-progress__item" :class="{ 'is-active': draftReady }">
        <span><el-icon><List /></el-icon></span>
        <div><strong>检查步骤</strong><small>操作与断言</small></div>
      </div>
      <i />
      <div class="composer-progress__item">
        <span><el-icon><VideoPlay /></el-icon></span>
        <div><strong>试运行</strong><small>结果与证据</small></div>
      </div>
    </div>

    <el-form v-if="!draftReady" ref="formRef" :model="localForm" :rules="rules" label-position="top" class="composer-form">
      <div class="composer-form__row">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="localForm.project_id" style="width: 100%" @change="emit('project-change', $event)">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标地址" prop="target_url">
          <el-input v-model="localForm.target_url" placeholder="https://example.com" clearable>
            <template #prefix><el-icon><Link /></el-icon></template>
          </el-input>
        </el-form-item>
      </div>

      <el-form-item label="测试目标" prop="goal" class="goal-field">
        <el-input
          v-model="localForm.goal"
          type="textarea"
          :rows="6"
          maxlength="4000"
          show-word-limit
          resize="none"
          placeholder="例如：打开目标地址，在搜索框输入 zyc123，点击查询，验证结果包含 zyc123"
        />
        <div class="goal-field__footer">
          <button type="button" class="example-action" @click="applyExample">
            <el-icon><DocumentCopy /></el-icon>
            使用示例
          </button>
        </div>
      </el-form-item>

      <button type="button" class="advanced-trigger" :aria-expanded="advancedVisible" @click="toggleAdvanced">
        <span><el-icon><Setting /></el-icon>高级设置</span>
        <span>{{ modeText(localForm.execution_mode) }} · 最多 {{ localForm.max_steps }} 步 <el-icon><ArrowDown :class="{ 'is-open': advancedVisible }" /></el-icon></span>
      </button>
      <el-collapse-transition>
        <div v-show="advancedVisible" ref="advancedPanelRef" class="advanced-panel">
          <el-form-item label="运行模式">
            <el-radio-group v-model="localForm.execution_mode" class="mode-selector">
              <el-radio-button v-for="item in executionModeOptions" :key="item.value" :value="item.value">{{ item.label }}</el-radio-button>
            </el-radio-group>
            <div class="field-help">{{ modeDescription(localForm.execution_mode) }}</div>
          </el-form-item>
          <div class="composer-form__row composer-form__row--advanced">
            <el-form-item label="补充上下文">
              <el-input v-model="localForm.context" type="textarea" :rows="3" maxlength="8000" resize="none" placeholder="测试数据、登录前置条件或已知约束" />
            </el-form-item>
            <el-form-item label="最多步骤">
              <el-input-number v-model="localForm.max_steps" :min="1" :max="30" controls-position="right" />
            </el-form-item>
          </div>
        </div>
      </el-collapse-transition>
    </el-form>

    <div v-else class="draft-review">
      <div class="draft-summary">
        <div>
          <span class="draft-summary__eyebrow">AI 草稿</span>
          <h3>{{ draft.name }}</h3>
          <p>{{ draft.target_url }}</p>
        </div>
        <div class="draft-summary__stats">
          <span><strong>{{ draft.steps?.length || 0 }}</strong> 操作</span>
          <span><strong>{{ (draft.assertions?.length || 0) + 1 }}</strong> 断言</span>
          <el-tag effect="plain">{{ modeText(draft.execution_mode) }}</el-tag>
        </div>
      </div>

      <div v-if="warnings.length" class="draft-notice">
        <el-icon><WarningFilled /></el-icon>
        <div><strong>{{ warnings.length }} 项需要留意</strong><span>{{ warnings[0] }}</span></div>
      </div>

      <section class="draft-section">
        <div class="draft-section__head"><h4>操作步骤</h4><span>{{ draft.steps?.length || 0 }} 步</span></div>
        <div class="draft-timeline">
          <div v-for="(step, index) in draft.steps || []" :key="step._key || index" class="draft-step">
            <span class="draft-step__index">{{ index + 1 }}</span>
            <span class="draft-step__icon"><el-icon><component :is="stepIcon(step.action)" /></el-icon></span>
            <div>
              <strong>{{ step.name || actionText(step.action) }}</strong>
              <p>{{ stepDescription(step) }}</p>
            </div>
            <el-tag size="small" effect="plain" type="info">{{ actionText(step.action) }}</el-tag>
          </div>
        </div>
      </section>

      <section class="draft-section draft-section--assertions">
        <div class="draft-section__head"><h4>通过条件</h4><span>{{ (draft.assertions?.length || 0) + 1 }} 项</span></div>
        <div class="assertion-list">
          <div class="assertion-item"><el-icon><CircleCheck /></el-icon><span>页面显示“{{ draft.expect_text }}”</span></div>
          <div v-for="(assertion, index) in draft.assertions || []" :key="assertion._key || index" class="assertion-item">
            <el-icon><CircleCheck /></el-icon>
            <span>{{ assertion.name || assertionText(assertion) }}</span>
          </div>
        </div>
      </section>
    </div>

    <template #footer>
      <div class="composer-footer">
        <template v-if="!draftReady">
          <span class="composer-footer__note">不会覆盖已有用例</span>
          <el-button @click="emit('update:modelValue', false)">取消</el-button>
          <el-button type="primary" :icon="MagicStick" :loading="generating" @click="requestGenerate">生成测试步骤</el-button>
        </template>
        <template v-else>
          <el-button :icon="ArrowLeft" @click="emit('reset')">返回修改</el-button>
          <span class="composer-footer__spacer" />
          <el-button :icon="EditPen" :disabled="saving || running" @click="emit('advanced-edit')">高级编辑</el-button>
          <el-button :loading="saving" :disabled="running" @click="emit('save')">仅保存</el-button>
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="saving" @click="emit('save-run')">保存并试运行</el-button>
        </template>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { nextTick, reactive, ref, watch } from 'vue'
import {
  ArrowDown, ArrowLeft, CircleCheck, DocumentCopy, EditPen, Link, List, MagicStick,
  Mouse, Position, Promotion, Search, Setting, VideoPlay, WarningFilled
} from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  form: { type: Object, required: true },
  projects: { type: Array, default: () => [] },
  draftReady: { type: Boolean, default: false },
  draft: { type: Object, default: null },
  warnings: { type: Array, default: () => [] },
  generating: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  running: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'update:form', 'project-change', 'generate', 'reset', 'advanced-edit', 'save', 'save-run'])
const formRef = ref(null)
const advancedPanelRef = ref(null)
const advancedVisible = ref(false)
const localForm = reactive({})
let syncingFromParent = false

watch(
  () => props.form,
  (value) => {
    syncingFromParent = true
    Object.assign(localForm, value || {})
    syncingFromParent = false
  },
  { deep: true, immediate: true }
)
watch(
  localForm,
  (value) => {
    if (!syncingFromParent) emit('update:form', { ...value })
  },
  { deep: true }
)

const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  target_url: [{ required: true, message: '请输入目标地址', trigger: 'blur' }],
  goal: [{ required: true, message: '请输入测试目标', trigger: 'blur' }, { min: 5, message: '测试目标至少 5 个字符', trigger: 'blur' }]
}

const executionModeOptions = [
  { label: '稳定回归', value: 'stable' },
  { label: '适应执行', value: 'adaptive' },
  { label: '自主探索', value: 'explore' },
  { label: '视觉测试', value: 'visual' }
]

const modeText = (mode) => ({ stable: '稳定回归', adaptive: '适应执行', explore: '自主探索', visual: '视觉测试' }[mode] || '适应执行')
const modeDescription = (mode) => ({
  stable: '优先使用确定性语义定位，适合日常回归。',
  adaptive: '页面发生变化时允许一次受控 AI 定位恢复。',
  explore: 'AI 在安全边界内按目标探索并记录发现。',
  visual: '增加多模态模型对布局和视觉结果的检查。'
}[mode] || '')

const actionLabels = {
  goto: '打开页面', fill: '填写内容', click: '点击元素', press: '按键', select_option: '选择选项',
  check: '勾选', uncheck: '取消勾选', hover: '悬停', wait_for_selector: '等待元素',
  wait_for_text: '等待文本', wait: '等待', set_viewport: '设置视口', assert_text: '验证文本',
  assert_visible: '验证可见', assert_hidden: '验证隐藏', assert_url_contains: '验证地址', assert_title_contains: '验证标题'
}
const actionText = (action) => actionLabels[action] || action
const stepIcon = (action) => {
  if (action === 'goto') return Promotion
  if (['fill', 'press', 'select_option'].includes(action)) return EditPen
  if (['assert_text', 'assert_visible', 'assert_hidden', 'assert_url_contains', 'assert_title_contains'].includes(action)) return Search
  if (action.startsWith('wait')) return Position
  return Mouse
}
const stepDescription = (step) => {
  if (step.action === 'goto') return step.value || props.draft?.target_url || '-'
  const target = step.target || step.accessible_name || step.label || step.placeholder || step.selector
  if (step.value && target) return `${target} · ${step.value}`
  return step.value || target || '由 AI 在执行时识别目标'
}
const assertionText = (assertion) => assertion.value || assertion.expected || assertion.target || assertion.type

const applyExample = () => {
  localForm.goal = '打开目标地址，在搜索框输入 zyc123，点击查询，验证查询结果包含 zyc123'
}
const toggleAdvanced = async () => {
  advancedVisible.value = !advancedVisible.value
  if (!advancedVisible.value) return
  await nextTick()
  window.setTimeout(() => advancedPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 180)
}
const requestGenerate = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (valid) emit('generate')
}
</script>

<style scoped>
.composer-header { display: flex; align-items: center; gap: 12px; padding-right: 38px; }
.composer-header__icon { width: 38px; height: 38px; flex: 0 0 38px; display: grid; place-items: center; border: 1px solid #c7d2fe; border-radius: 8px; background: #eef2ff; color: #4f46e5; font-size: 19px; }
.composer-header > div { min-width: 0; display: flex; flex: 1; flex-direction: column; gap: 3px; }
.composer-header strong { color: #172033; font-size: 17px; line-height: 1.25; }
.composer-header span { color: #667085; font-size: 12px; }
.composer-progress { display: grid; grid-template-columns: auto minmax(30px, 1fr) auto minmax(30px, 1fr) auto; align-items: center; padding: 16px 18px; border-bottom: 1px solid #e7eaf0; background: #f8fafc; }
.composer-progress > i { height: 1px; margin: 0 18px; background: #dce1ea; }
.composer-progress > i.is-active { background: #818cf8; }
.composer-progress__item { display: flex; align-items: center; gap: 9px; color: #98a2b3; }
.composer-progress__item > span { width: 30px; height: 30px; display: grid; place-items: center; border: 1px solid #dce1ea; border-radius: 50%; background: #fff; }
.composer-progress__item div { display: flex; flex-direction: column; gap: 2px; }
.composer-progress__item strong { font-size: 12px; line-height: 1.2; }
.composer-progress__item small { font-size: 10px; white-space: nowrap; }
.composer-progress__item.is-complete, .composer-progress__item.is-active { color: #4338ca; }
.composer-progress__item.is-complete > span, .composer-progress__item.is-active > span { border-color: #a5b4fc; background: #eef2ff; }
.composer-form { padding: 24px 26px 12px; }
.composer-form__row { display: grid; grid-template-columns: minmax(180px, .75fr) minmax(300px, 1.45fr); gap: 16px; }
.composer-form__row--advanced { grid-template-columns: minmax(0, 1fr) 160px; }
.goal-field__footer { width: 100%; display: flex; justify-content: flex-start; margin-top: 7px; }
.example-action { display: inline-flex; align-items: center; gap: 5px; border: 0; padding: 2px 0; background: transparent; color: #4f46e5; font-size: 12px; cursor: pointer; }
.example-action:hover { color: #3730a3; }
.advanced-trigger { width: 100%; min-height: 46px; display: flex; align-items: center; justify-content: space-between; border: 1px solid #e4e7ed; padding: 0 14px; background: #fff; color: #344054; cursor: pointer; }
.advanced-trigger:hover { border-color: #a5b4fc; }
.advanced-trigger span { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; }
.advanced-trigger span:last-child { color: #667085; }
.advanced-trigger .el-icon { transition: transform .18s ease; }
.advanced-trigger .el-icon.is-open { transform: rotate(180deg); }
.advanced-panel { padding: 18px 16px 2px; border: 1px solid #e4e7ed; border-top: 0; background: #f8fafc; }
.mode-selector { width: 100%; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.mode-selector :deep(.el-radio-button) { min-width: 0; }
.mode-selector :deep(.el-radio-button__inner) { width: 100%; border-radius: 0; }
.field-help { margin-top: 7px; color: #667085; font-size: 12px; }
.draft-review { max-height: 61vh; overflow: auto; padding: 22px 26px 14px; }
.draft-summary { display: flex; justify-content: space-between; gap: 24px; padding-bottom: 18px; border-bottom: 1px solid #e7eaf0; }
.draft-summary__eyebrow { color: #4f46e5; font-size: 11px; font-weight: 700; }
.draft-summary h3 { margin: 4px 0 5px; color: #172033; font-size: 18px; letter-spacing: 0; }
.draft-summary p { max-width: 520px; margin: 0; color: #667085; font-size: 12px; overflow-wrap: anywhere; }
.draft-summary__stats { display: flex; align-items: center; gap: 10px; color: #667085; font-size: 12px; white-space: nowrap; }
.draft-summary__stats span { padding-right: 10px; border-right: 1px solid #e4e7ed; }
.draft-summary__stats strong { color: #172033; }
.draft-notice { display: flex; align-items: flex-start; gap: 10px; margin-top: 16px; border: 1px solid #fed7aa; padding: 11px 12px; background: #fff7ed; color: #c2410c; }
.draft-notice div { display: flex; flex-direction: column; gap: 3px; }
.draft-notice strong { font-size: 12px; }
.draft-notice span { color: #9a3412; font-size: 11px; }
.draft-section { margin-top: 20px; }
.draft-section__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.draft-section__head h4 { margin: 0; color: #172033; font-size: 13px; }
.draft-section__head span { color: #98a2b3; font-size: 11px; }
.draft-timeline { border: 1px solid #e4e7ed; background: #fff; }
.draft-step { min-height: 58px; display: grid; grid-template-columns: 26px 30px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 8px 12px; border-bottom: 1px solid #edf0f4; }
.draft-step:last-child { border-bottom: 0; }
.draft-step__index { color: #98a2b3; font-size: 11px; text-align: center; }
.draft-step__icon { width: 28px; height: 28px; display: grid; place-items: center; border: 1px solid #d8defd; border-radius: 6px; background: #f3f4ff; color: #4f46e5; }
.draft-step div { min-width: 0; }
.draft-step strong { display: block; color: #344054; font-size: 12px; }
.draft-step p { margin: 3px 0 0; color: #667085; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.draft-section--assertions { margin-bottom: 4px; }
.assertion-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #bbebd4; background: #f2fbf7; }
.assertion-item { min-height: 44px; display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid #d9f3e6; color: #166534; font-size: 12px; }
.assertion-item:nth-child(odd) { border-right: 1px solid #d9f3e6; }
.assertion-item .el-icon { flex: 0 0 auto; color: #16a34a; }
.composer-footer { width: 100%; display: flex; align-items: center; gap: 10px; }
.composer-footer__note { margin-right: auto; color: #98a2b3; font-size: 11px; }
.composer-footer__spacer { flex: 1; }

:global(.ai-composer-dialog) { max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; border-radius: 8px; }
:global(.ai-composer-dialog .el-dialog__header) { margin: 0; padding: 18px 22px; border-bottom: 1px solid #e7eaf0; }
:global(.ai-composer-dialog .el-dialog__body) { min-height: 0; overflow: auto; padding: 0; }
:global(.ai-composer-dialog .el-dialog__footer) { padding: 14px 22px; border-top: 1px solid #e7eaf0; background: #fff; }
:global(.ai-composer-dialog .el-textarea__inner) { line-height: 1.75; }
:global(.ai-composer-dialog .el-input-number) { width: 100%; }

@media (max-width: 720px) {
  .composer-header > .el-tag { display: none; }
  .composer-progress { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
  .composer-progress > i { display: none; }
  .composer-progress__item { justify-content: center; }
  .composer-progress__item small { display: none; }
  .composer-form { padding: 18px 16px 8px; }
  .composer-form__row, .composer-form__row--advanced { grid-template-columns: 1fr; gap: 0; }
  .advanced-trigger > span:last-child { display: none; }
  .mode-selector { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mode-selector :deep(.el-radio-button:nth-child(3) .el-radio-button__inner) { border-left: 1px solid var(--el-border-color); }
  .draft-review { padding: 18px 16px 10px; }
  .draft-summary { flex-direction: column; gap: 12px; }
  .draft-summary__stats { flex-wrap: wrap; }
  .draft-step { grid-template-columns: 24px 28px minmax(0, 1fr); }
  .draft-step > .el-tag { display: none; }
  .assertion-list { grid-template-columns: 1fr; }
  .assertion-item:nth-child(odd) { border-right: 0; }
  .composer-footer { flex-wrap: wrap; }
  .composer-footer__spacer { display: none; }
  .composer-footer .el-button { flex: 1; margin: 0; }
}
</style>
