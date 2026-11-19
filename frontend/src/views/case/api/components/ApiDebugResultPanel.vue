<template>
  <div v-if="debugResponse" class="debug-response">
    <div class="debug-metrics">
      <el-tag :type="debugResponse.response.status_code < 400 ? 'success' : 'danger'">
        {{ debugResponse.response.status_code }}
      </el-tag>
      <el-tag
        v-if="debugResponse.assertion_passed !== null && debugResponse.assertion_passed !== undefined"
        :type="debugResponse.assertion_passed ? 'success' : 'danger'"
        effect="plain"
      >
        {{ debugResponse.assertion_passed ? '断言通过' : '断言失败' }}
      </el-tag>
      <span>{{ debugResponse.duration_ms }} ms</span>
      <span>{{ debugResponse.response.size }} bytes</span>
      <span>{{ debugResponse.request.method }} {{ debugResponse.request.url }}</span>
    </div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="Body" name="body">
        <pre class="response-pre">{{ formatBody(debugResponse.response.body) }}</pre>
      </el-tab-pane>
      <el-tab-pane
        v-if="debugResponse.step_results?.length"
        :label="`场景步骤 (${debugResponse.step_results.length})`"
        name="steps"
      >
        <div class="debug-assertion-list">
          <div v-for="step in debugResponse.step_results" :key="'step-' + step.index" class="debug-assertion-item">
            <el-tag size="small" :type="step.status === 'SUCCESS' ? 'success' : 'danger'">{{ step.status }}</el-tag>
            <strong>#{{ step.index }} {{ step.name }}</strong>
            <span>{{ step.request?.method }} {{ step.request?.url }} ({{ step.duration_ms }} ms)</span>
          </div>
        </div>
      </el-tab-pane>
      <el-tab-pane
        v-if="debugResponse.assertion_results?.length || debugResponse.extractor_results?.length"
        label="断言/提取"
        name="assertions"
      >
        <div class="debug-assertion-list">
          <div v-for="(item, index) in debugResponse.assertion_results" :key="'a' + index" class="debug-assertion-item">
            <el-tag size="small" :type="item.ok ? 'success' : 'danger'">{{ item.ok ? 'PASS' : 'FAIL' }}</el-tag>
            <span>{{ item.message }}</span>
          </div>
          <template v-if="debugResponse.extractor_results?.length">
            <el-divider content-position="left">变量提取</el-divider>
            <div v-for="(item, index) in debugResponse.extractor_results" :key="'e' + index" class="debug-assertion-item">
              <el-tag size="small" :type="item.ok ? 'success' : 'danger'">{{ item.ok ? 'PASS' : 'FAIL' }}</el-tag>
              <span>{{ item.message }}</span>
            </div>
          </template>
        </div>
      </el-tab-pane>
      <el-tab-pane label="Headers" name="headers">
        <pre class="response-pre">{{ JSON.stringify(debugResponse.response.headers, null, 2) }}</pre>
      </el-tab-pane>
      <el-tab-pane label="Request" name="request">
        <pre class="response-pre">{{ JSON.stringify(debugResponse.request, null, 2) }}</pre>
      </el-tab-pane>
    </el-tabs>
  </div>
  <div v-else class="debug-empty">
    <div class="debug-empty-title">调试结果会显示在这里</div>
    <div class="debug-empty-text">先选择调试环境和超时，再点击 Send 查看响应、Headers 和实际请求。</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatDebugBody } from '../apiCaseUtils'

const props = defineProps({
  debugResponse: {
    type: Object,
    default: null
  },
  modelValue: {
    type: String,
    default: 'body'
  }
})

const emit = defineEmits(['update:modelValue'])

const activeTab = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const formatBody = (body) => formatDebugBody(body)
</script>
