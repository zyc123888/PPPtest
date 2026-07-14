import { api } from '@/lib/api'

export function listCaseGenerationV2Jobs(options = {}) {
  const params = new URLSearchParams()
  if (options.projectId) params.set('project_id', options.projectId)
  if (options.status) params.set('status', options.status)
  if (options.mode) params.set('mode', options.mode)
  if (options.pipelineMode) params.set('pipeline_mode', options.pipelineMode)
  if (options.createdAfter) params.set('created_after', options.createdAfter)
  if (options.createdBefore) params.set('created_before', options.createdBefore)
  if (options.beforeId) params.set('before_id', options.beforeId)
  if (options.limit) params.set('limit', options.limit)
  const query = params.toString()
  return api.get(`/case-generation-v2/jobs${query ? `?${query}` : ''}`)
}

export function getCaseGenerationV2JobDetail(jobId) {
  return api.get(`/case-generation-v2/jobs/${jobId}`)
}

export function createCaseGenerationV2Job(payload) {
  return api.post('/case-generation-v2/jobs', payload)
}

export function getCaseGenerationV2ModelConfig(workspaceId) {
  return api.get(`/case-generation/model-config?workspace_id=${workspaceId}`)
}

export function listCaseGenerationV2ModelOptions() {
  return api.get('/case-generation/model-options')
}

export function saveCaseGenerationV2ModelConfig(payload) {
  return api.post('/case-generation/model-config', payload)
}

export function rerunCaseGenerationV2Job(jobId) {
  return api.post(`/case-generation-v2/jobs/${jobId}/rerun`, {})
}

export function rerunCaseGenerationV2SourceShard(jobId, sourceId) {
  return api.post(`/case-generation-v2/jobs/${jobId}/shards/${encodeURIComponent(sourceId)}/rerun`, {})
}

export function cancelCaseGenerationV2Job(jobId) {
  return api.post(`/case-generation-v2/jobs/${jobId}/cancel`, {})
}

export function downloadCaseGenerationV2Artifact(jobId, artifactId) {
  return api.getBlob(`/case-generation-v2/jobs/${jobId}/artifacts/${artifactId}/download`)
}

export function getCaseGenerationV2Artifact(jobId, artifactId) {
  return api.get(`/case-generation-v2/jobs/${jobId}/artifacts/${artifactId}`)
}

export function caseGenerationV2StatusTagType(status) {
  if (status === 'SUCCESS') return 'success'
  if (status === 'CONDITIONAL') return 'warning'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'info'
  if (status === 'RUNNING') return 'warning'
  return 'info'
}

const ARTIFACT_LABELS = {
  source_manifest: 'SourceManifest',
  evidence_trace: '证据追踪',
  evidence_trace_gate: '证据门禁',
  scope_index: '范围索引',
  scope_index_gate: '范围门禁',
  function_points: '功能点',
  requirement_handoff: '需求门禁',
  testcase_base_package: '基线用例包',
  testcase_package: '用例包',
  testcase_handoff: '用例门禁',
  trusted_review_report: '可信复核',
  review_report: '复核报告',
  markdown: 'Markdown',
  xmindmark: 'XMindMark',
  xmind: 'XMind',
  final_delivery_gate: '交付门禁',
  model_call_trace: '模型调用追踪',
  xmind_export_log: 'XMind Log'
}

export function caseGenerationV2ArtifactLabel(artifact) {
  return ARTIFACT_LABELS[artifact?.artifact_type] || artifact?.artifact_type || '-'
}

export function formatCaseGenerationV2ArtifactContent(artifact) {
  if (artifact?.content_json) {
    return JSON.stringify(artifact.content_json, null, 2)
  }
  if (artifact?.file_name?.endsWith('.md')) {
    return 'Markdown 摘要文件，请点击下载查看。'
  }
  return artifact?.expired_at ? '该产物已按保留策略过期' : '暂无预览'
}
