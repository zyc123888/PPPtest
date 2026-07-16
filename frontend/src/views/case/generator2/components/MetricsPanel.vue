<template>
  <div v-if="generationMetrics" class="metrics-comparison">
    <div class="metrics-comparison__head">
      <strong>真实运行指标</strong>
      <span v-if="metricsComparison?.baseline_job_id">对比 V1 #{{ metricsComparison.baseline_job_id }}</span>
      <span v-else>暂无同项目 V1 基线</span>
    </div>
    <div class="metrics-comparison__grid">
      <div class="trusted-metric">
        <span>总耗时</span>
        <strong>{{ formatDurationMs(generationMetrics.duration_ms) || '-' }}</strong>
        <small v-if="metricDelta('duration_ms') !== null">{{ formatMetricDelta('duration_ms', '耗时') }}</small>
      </div>
      <div class="trusted-metric">
        <span>模型调用</span>
        <strong>{{ generationMetrics.model_call_count ?? 0 }}</strong>
        <small v-if="metricDelta('model_call_count') !== null">{{ formatMetricDelta('model_call_count', '次') }}</small>
      </div>
      <div class="trusted-metric">
        <span>Token</span>
        <strong>{{ formatInteger(generationMetrics.total_tokens) }}</strong>
        <small v-if="metricDelta('total_tokens') !== null">{{ formatMetricDelta('total_tokens', '') }}</small>
      </div>
      <div class="trusted-metric">
        <span>用例数</span>
        <strong>{{ generationMetrics.testcase_count ?? 0 }}</strong>
        <small v-if="metricDelta('testcase_count') !== null">{{ formatMetricDelta('testcase_count', '条') }}</small>
      </div>
      <div class="trusted-metric">
        <span>重复率</span>
        <strong>{{ formatRate(generationMetrics.duplicate_rate) }}</strong>
        <small v-if="metricDelta('duplicate_rate') !== null">{{ formatRateDelta(metricDelta('duplicate_rate')) }}</small>
      </div>
      <div class="trusted-metric">
        <span>弱预期率</span>
        <strong>{{ formatRate(generationMetrics.weak_expected_rate) }}</strong>
        <small v-if="metricDelta('weak_expected_rate') !== null">{{ formatRateDelta(metricDelta('weak_expected_rate')) }}</small>
      </div>
    </div>
  </div>

  <div v-if="trusted && trustedMetrics" class="trusted-metrics">
    <div v-for="metric in coreMetricRows" :key="metric.label" class="trusted-metric">
      <span>{{ metric.label }}</span>
      <strong>{{ formatTrustedMetric(metric) }}</strong>
    </div>
    <div v-for="metric in visibleIssueRows" :key="metric.label" class="trusted-metric trusted-metric--issue">
      <span>{{ metric.label }}</span>
      <strong>{{ formatTrustedMetric(metric) }}</strong>
    </div>
    <div class="trusted-metric trusted-metric--wide">
      <span>gate 结论</span>
      <el-tag :type="trustedMetrics.gate_passed ? ((trustedMetrics.gate_warning_count ?? 0) > 0 ? 'warning' : 'success') : 'danger'">
        {{ trustedMetrics.gate_passed ? (((trustedMetrics.gate_warning_count ?? 0) > 0) ? '有风险通过' : '通过') : '未通过' }}
      </el-tag>
    </div>
    <div class="trusted-metric trusted-metric--wide">
      <span>语义审查</span>
      <el-tag :type="trustedMetrics.semantic_release_readiness === 'pass' ? 'success' : 'warning'">
        {{ trustedMetrics.semantic_release_readiness || '-' }}
      </el-tag>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatRate } from '@/lib/caseGenerationUi'
import { formatDurationMs } from '../presentation'

const props = defineProps({
  generationMetrics: { type: Object, default: null },
  metricsComparison: { type: Object, default: null },
  trustedMetrics: { type: Object, default: null },
  trusted: { type: Boolean, default: false }
})

// 核心指标：反映规模与健康度，始终显示
const coreMetricRows = [
  { label: '直接测试对象数', keys: ['source_count'] },
  { label: '功能点数', keys: ['function_point_count'] },
  { label: 'FP 回执完整率', keys: ['function_point_receipt_rate', 'function_point_consumption_rate'], rate: true },
  { label: '结构追溯完整率', keys: ['source_traceability_rate', 'source_with_testcase_rate', 'source_coverage_rate'], rate: true },
  { label: '预期依据完整率', keys: ['assertion_basis_rate'], rate: true },
  { label: 'must_cover 语义覆盖', keys: ['semantic_must_cover_rate'], rate: true },
  { label: '图片证据用例率', keys: ['concrete_image_evidence_rate'], rate: true },
  { label: '待确认数量', keys: ['pending_confirmation_count'] }
]

// 问题指标：正常为 0，仅当出现（> 0）时才显示，避免堆砌零值噪音
const issueMetricRows = [
  { label: 'must_cover 缺口', keys: ['must_cover_gap_count'] },
  { label: '方法消费缺口', keys: ['method_gap_count'] },
  { label: '弱预期数量', keys: ['weak_expected_count'] },
  { label: '模糊步骤数', keys: ['ambiguous_step_count'] },
  { label: '不可验证预期', keys: ['unverifiable_expectation_count'] },
  { label: '无依据断言', keys: ['unsupported_assertion_count'] },
  { label: '证据错绑', keys: ['evidence_mismatch_count'] },
  { label: '旧状态误作预期', keys: ['current_state_as_expected_count'] },
  { label: '精确验收值丢失', keys: ['exact_value_loss_count'] },
  { label: '重复合并数', keys: ['duplicate_case_count'] },
  { label: '门禁阻断数', keys: ['gate_blocker_count'] },
  { label: '风险提示数', keys: ['gate_warning_count'] }
]

const visibleIssueRows = computed(() =>
  issueMetricRows.filter((metric) => Number(resolveMetricValue(metric.keys)) > 0)
)

function resolveMetricValue(keys) {
  for (const key of keys) {
    const value = props.trustedMetrics?.[key]
    if (value !== null && value !== undefined) return value
  }
  return null
}

function formatTrustedMetric(metric) {
  const value = resolveMetricValue(metric.keys)
  return metric.rate ? formatRate(value) : (value ?? 0)
}

function metricDelta(key) {
  const value = props.metricsComparison?.delta?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatInteger(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.round(number).toLocaleString('zh-CN') : '-'
}

function formatMetricDelta(key, unit) {
  const value = metricDelta(key)
  if (value === null) return ''
  if (key === 'duration_ms') {
    const sign = value > 0 ? '+' : (value < 0 ? '-' : '')
    return `较 V1 ${sign}${formatDurationMs(Math.abs(value)) || '0s'}`
  }
  const sign = value > 0 ? '+' : ''
  return `较 V1 ${sign}${formatInteger(value)}${unit}`
}

function formatRateDelta(value) {
  if (value === null) return ''
  const points = value * 100
  return `较 V1 ${points > 0 ? '+' : ''}${points.toFixed(1)} 个百分点`
}
</script>

<style scoped>
.metrics-comparison,
.trusted-metrics {
  margin-bottom: 14px;
}

.metrics-comparison {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(20, 184, 166, 0.2);
  border-radius: 8px;
  background: rgba(240, 253, 250, 0.7);
}

.metrics-comparison__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.metrics-comparison__head span,
.metrics-comparison small {
  color: var(--color-text-secondary);
  font-size: 11px;
}

.metrics-comparison__grid,
.trusted-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.trusted-metric {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.78);
}

.trusted-metric span {
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.3;
}

.trusted-metric strong {
  font-size: 18px;
  line-height: 1.1;
}

.trusted-metric--issue {
  border-color: rgba(245, 158, 11, 0.35);
  background: rgba(255, 251, 235, 0.85);
}

.trusted-metric--issue strong {
  color: #d97706;
}

.trusted-metric--wide {
  grid-column: span 3;
  grid-template-columns: 1fr auto;
  align-items: center;
}

@media (max-width: 768px) {
  .metrics-comparison__grid,
  .trusted-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .trusted-metric--wide {
    grid-column: span 2;
  }
}
</style>
