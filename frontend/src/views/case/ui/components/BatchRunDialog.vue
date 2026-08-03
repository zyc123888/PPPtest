<template>
  <el-dialog :model-value="modelValue" :title="title" width="560px" @update:model-value="$emit('update:modelValue', $event)">
    <p class="batch-run-hint">已选择 <strong>{{ count }}</strong> 条用例，将按顺序依次执行并生成集合报告。</p>
    <el-form label-position="top" :model="form">
      <el-form-item label="执行环境">
        <el-select v-model="form.environment_id" clearable placeholder="直接使用用例目标地址" style="width: 100%">
          <el-option v-for="item in environments" :key="item.id" :label="`${item.name} · ${item.base_url}`" :value="item.id" />
        </el-select>
      </el-form-item>
      <div class="batch-run-options">
        <el-form-item label="单用例超时（秒）">
          <el-input-number v-model="form.timeout_seconds" :min="1" :max="600" controls-position="right" />
        </el-form-item>
        <el-form-item label="自动重试">
          <el-input-number v-model="form.max_retries" :min="0" :max="3" controls-position="right" />
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">开始批量执行</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  environments: { type: Array, default: () => [] },
  count: { type: Number, default: 0 },
  submitting: { type: Boolean, default: false },
  title: { type: String, default: '批量执行 UI 用例' }
})
const emit = defineEmits(['update:modelValue', 'submit'])

const form = reactive({ environment_id: undefined, timeout_seconds: 60, max_retries: 0 })

watch(() => props.modelValue, (visible) => {
  if (visible) Object.assign(form, { environment_id: undefined, timeout_seconds: 60, max_retries: 0 })
})

const submit = () => {
  emit('submit', {
    environment_id: form.environment_id ?? null,
    timeout_seconds: form.timeout_seconds,
    max_retries: form.max_retries
  })
}
</script>

<style scoped>
.batch-run-hint { margin: 0 0 14px; color: var(--color-text-secondary); font-size: 13px; }
.batch-run-hint strong { color: var(--el-color-primary); }
.batch-run-options { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.batch-run-options :deep(.el-input-number) { width: 100%; }
</style>
