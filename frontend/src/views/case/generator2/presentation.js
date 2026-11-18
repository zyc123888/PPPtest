const GENERATION_DENSITY_LABELS = {
  concise: '精简',
  balanced: '均衡',
  exhaustive: '全面'
}

const SCOPE_INDEX_STRATEGY_LABELS = {
  single_full: '单次完整索引',
  section_batches_full: '完整分批索引',
  section_batches_lightweight: '长文档轻量索引',
  section_batches_full_after_timeout: '超时后分批索引'
}

const TRUSTED_ARTIFACT_TYPES = new Set([
  'source_manifest',
  'evidence_trace',
  'evidence_trace_gate',
  'scope_index',
  'scope_index_gate',
  'function_points',
  'requirement_handoff',
  'testcase_base_package',
  'testcase_package',
  'testcase_handoff',
  'trusted_review_report',
  'markdown',
  'xmindmark',
  'xmind',
  'final_delivery_gate',
  'model_call_trace',
  'generation_metrics',
  'xmind_export_log'
])

const LITE_ARTIFACT_TYPES = new Set(['xmind', 'xmind_export_log', 'generation_metrics'])

const TRUSTED_ARTIFACT_STAGE_KEYS = {
  model_call_trace: 'orchestrate',
  evidence_trace: 'evidence_trace',
  evidence_trace_gate: 'evidence_trace',
  source_manifest: 'scope_index',
  scope_index: 'scope_index',
  scope_index_gate: 'scope_index_gate',
  function_points: 'requirement',
  requirement_handoff: 'requirement_gate',
  testcase_base_package: 'testcase_by_source_shard',
  testcase_package: 'testcase_by_source_shard',
  testcase_handoff: 'testcase_gate',
  trusted_review_report: 'quality_review',
  generation_metrics: 'quality_review',
  markdown: 'export',
  xmindmark: 'export',
  final_delivery_gate: 'final_delivery_gate'
}

const LITE_ARTIFACT_STAGE_KEYS = {
  generation_metrics: 'review'
}

const GATE_ARTIFACTS = [
  { key: 'evidence_trace_gate', label: '证据门禁', payloadKey: '' },
  { key: 'scope_index_gate', label: '范围门禁', payloadKey: 'scope_index_gate' },
  { key: 'requirement_handoff', label: '需求门禁', payloadKey: 'requirement_gate' },
  { key: 'testcase_handoff', label: '用例门禁', payloadKey: 'testcase_gate' },
  { key: 'final_delivery_gate', label: '交付门禁', payloadKey: '' }
]

export function jobPipelineMode(job) {
  return job?.input_payload_json?.pipeline_mode || 'lite'
}

export function trustedGenerationStrategyLabel(strategy) {
  return strategy === 'lite_review' ? '轻量结果审查' : '按 source 分片'
}

export function generationDensityLabel(density) {
  return GENERATION_DENSITY_LABELS[density || 'balanced'] || '均衡'
}

export function scopeIndexStrategyLabel(mode) {
  return SCOPE_INDEX_STRATEGY_LABELS[mode] || mode || '范围索引'
}

export function formatScopeIndexStrategy(strategy) {
  if (!strategy) return ''
  const sections = Number(strategy.section_count || 0)
  const batches = Number(strategy.batch_count || 0)
  const concurrency = Number(strategy.concurrency || 0)
  const parts = [scopeIndexStrategyLabel(strategy.mode)]
  if (sections) parts.push(`${sections} 章节`)
  if (batches > 1) parts.push(`${batches} 批`)
  if (concurrency > 1) parts.push(`并发 ${concurrency}`)
  if (strategy.uses_lightweight_discovery) parts.push('轻量识别')
  return parts.join(' · ')
}

export function hasSourceGap(source) {
  return ['gap', 'missing', 'blocked'].includes(source?.must_cover_status) ||
    ['gap', 'missing', 'blocked'].includes(source?.method_consumption_status)
}

export function sourceStatusTag(status) {
  if (['covered', 'pass', 'ok'].includes(status)) return 'success'
  if (['gap', 'missing', 'blocked'].includes(status)) return 'warning'
  return 'info'
}

export function canRerunSourceShard(job, trusted, source) {
  if (!job || !trusted || !source?.source_id) return false
  if (['RUNNING', 'PENDING'].includes(job.status)) return false
  return job.status === 'FAILED' ||
    source.shard_status === 'failed' ||
    hasSourceGap(source) ||
    (Array.isArray(source.gate_issues) && source.gate_issues.length > 0)
}

export function formatJobListSummary(job) {
  const summary = String(job?.summary || '').trim()
  if (!summary) return '暂无摘要'

  const generatedMatch = summary.match(/已生成\s*(\d+)\s*条用例/)
  const suggestionMatch = summary.match(/(\d+)\s*项改进建议/)
  if (!generatedMatch) return summary

  const parts = [`${generatedMatch[1]} 条用例`]
  if (summary.includes('有条件通过')) {
    parts.push('条件通过')
  } else if (summary.includes('导出 XMind')) {
    parts.push('已导出 XMind')
  }
  if (suggestionMatch) parts.push(`${suggestionMatch[1]} 项建议`)
  return parts.join(' · ')
}

export function formatRecoveryPlan(plan, stageLabels = {}) {
  if (!plan?.strategy || plan.strategy === 'none') return ''
  const strategyLabel = {
    local_rerun: '局部重跑',
    stage_rerun: '阶段重跑'
  }[plan.strategy] || plan.strategy
  const returnTo = plan.return_to ? `退回 ${stageLabels[plan.return_to] || plan.return_to}` : ''
  const sourceIds = Array.isArray(plan.rerun_scope?.source_ids)
    ? plan.rerun_scope.source_ids.filter(Boolean)
    : []
  const sourceText = sourceIds.length
    ? `影响 ${sourceIds.slice(0, 4).join('、')}${sourceIds.length > 4 ? ` 等 ${sourceIds.length} 个 source` : ''}`
    : ''
  return [strategyLabel, returnTo, sourceText].filter(Boolean).join(' / ')
}

export function buildTrustedGateIssues(artifacts, stageLabels = {}, recoveryActions = []) {
  const artifactList = Array.isArray(artifacts) ? artifacts : []
  const availableActions = Array.isArray(recoveryActions) ? recoveryActions : []
  return GATE_ARTIFACTS
    .map((gate) => {
      const artifact = artifactList.find((item) => item.artifact_type === gate.key)
      const content = artifact?.content_json || {}
      const payload = gate.payloadKey ? (content?.[gate.payloadKey] || content) : content
      const issues = Array.isArray(payload?.issues)
        ? payload.issues.filter((item) => item && (item.severity || item.code || item.message)).slice(0, 6)
        : []
      if (!issues.length) return null

      const issueCounts = payload?.issue_counts || {}
      const blockingCount = Number(issueCounts.blocker ?? issues.filter((item) => item.severity === 'blocker').length)
      const warningCount = Number(issueCounts.warning ?? issues.filter((item) => item.severity === 'warning').length)
      const infoCount = issues.filter((item) => !['blocker', 'warning'].includes(item.severity)).length
      const hasActionableIssue = blockingCount > 0 || warningCount > 0
      const recoveryPlan = payload?.recovery_plan
      const sourceIds = Array.isArray(recoveryPlan?.rerun_scope?.source_ids)
        ? recoveryPlan.rerun_scope.source_ids.filter(Boolean).slice(0, 6)
        : []
      const gateActions = availableActions.filter((action) => {
        if (action?.gate_artifact_type !== gate.key) return false
        if (action.action === 'rerun_source') return sourceIds.includes(action.source_id)
        return action.action === 'rerun_job'
      })

      return {
        key: gate.key,
        label: gate.label,
        issues,
        blockingCount,
        warningCount,
        infoCount,
        tagType: blockingCount > 0 ? 'danger' : (warningCount > 0 ? 'warning' : 'info'),
        statusText: blockingCount > 0
          ? `${blockingCount} 项阻断`
          : (warningCount > 0 ? `${warningCount} 项风险` : `${infoCount || issues.length} 项提示`),
        recoveryPlan,
        recoveryText: hasActionableIssue ? formatRecoveryPlan(recoveryPlan, stageLabels) : '',
        sourceIds,
        recoveryActions: gateActions,
        canRerunStage: blockingCount > 0 && gateActions.some((action) => action.action === 'rerun_job')
      }
    })
    .filter(Boolean)
}

export function filterVisibleArtifacts(artifacts, trusted) {
  const allowedTypes = trusted ? TRUSTED_ARTIFACT_TYPES : LITE_ARTIFACT_TYPES
  return (Array.isArray(artifacts) ? artifacts : []).filter((item) => allowedTypes.has(item.artifact_type))
}

export function filterStageArtifacts(artifacts, stageKey, trusted) {
  if (!stageKey) return []
  const stageKeys = trusted ? TRUSTED_ARTIFACT_STAGE_KEYS : LITE_ARTIFACT_STAGE_KEYS
  return filterVisibleArtifacts(artifacts, trusted).filter(
    (artifact) => stageKeys[artifact.artifact_type] === stageKey
  )
}

export function mergeArtifactPreviewContent(artifacts, cachedArtifacts, preserveCached = true) {
  const cachedContent = preserveCached
    ? new Map((Array.isArray(cachedArtifacts) ? cachedArtifacts : []).map((item) => [item.id, item]))
    : new Map()
  return (Array.isArray(artifacts) ? artifacts : []).map((item) => {
    const cached = cachedContent.get(item.id)
    const sameRevision = Boolean(item.revision) && item.revision === cached?.revision
    return {
      ...item,
      content_json: item.content_json ?? (sameRevision ? cached?.content_json : null) ?? null
    }
  })
}

export function resolveActiveArtifactType(artifacts, preferredType = '') {
  const artifactList = Array.isArray(artifacts) ? artifacts : []
  return artifactList.some((item) => item.artifact_type === preferredType)
    ? preferredType
    : artifactList[0]?.artifact_type || ''
}

export function resolveFinalDeliveryGatePassed(artifact, trustedMetrics) {
  const artifactValue = artifact?.content_json?.passed
  if (typeof artifactValue === 'boolean') return artifactValue
  const metricValue = trustedMetrics?.final_delivery_gate_passed
  return typeof metricValue === 'boolean' ? metricValue : null
}

export function formatDurationMs(durationMs) {
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
