import { api } from '@/lib/api'

export function listCaseGenerationJobs(options = {}) {
  const params = new URLSearchParams()
  if (options.projectId) params.set('project_id', options.projectId)
  if (options.status) params.set('status', options.status)
  if (options.mode) params.set('mode', options.mode)
  if (options.createdAfter) params.set('created_after', options.createdAfter)
  if (options.createdBefore) params.set('created_before', options.createdBefore)
  if (options.beforeId) params.set('before_id', options.beforeId)
  if (options.limit) params.set('limit', options.limit)
  const query = params.toString()
  return api.get(`/case-generation/jobs${query ? `?${query}` : ''}`)
}

export function getCaseGenerationJobDetail(jobId) {
  return api.get(`/case-generation/jobs/${jobId}`)
}

export function createCaseGenerationJob(payload) {
  return api.post('/case-generation/jobs', payload)
}

export function getCaseGenerationModelConfig(workspaceId) {
  return api.get(`/case-generation/model-config?workspace_id=${workspaceId}`)
}

export function listCaseGenerationModelOptions() {
  return api.get('/case-generation/model-options')
}

export function saveCaseGenerationModelConfig(payload) {
  return api.post('/case-generation/model-config', payload)
}

export function rerunCaseGenerationJob(jobId) {
  return api.post(`/case-generation/jobs/${jobId}/rerun`, {})
}

export function cancelCaseGenerationJob(jobId) {
  return api.post(`/case-generation/jobs/${jobId}/cancel`, {})
}

export function downloadCaseGenerationArtifact(jobId, artifactId) {
  return api.getBlob(`/case-generation/jobs/${jobId}/artifacts/${artifactId}/download`)
}

export function getCaseGenerationArtifact(jobId, artifactId) {
  return api.get(`/case-generation/jobs/${jobId}/artifacts/${artifactId}`)
}

export function caseGenerationStatusTagType(status) {
  if (status === 'SUCCESS') return 'success'
  if (status === 'CONDITIONAL') return 'warning'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'info'
  if (status === 'RUNNING') return 'warning'
  return 'info'
}

const ARTIFACT_LABELS = { xmind: 'XMind', xmind_export_log: 'XMind Log', model_call_trace: '模型调用追踪' }

export function caseGenerationArtifactLabel(artifact) {
  return ARTIFACT_LABELS[artifact?.artifact_type] || artifact?.artifact_type || '-'
}

export function formatCaseGenerationArtifactContent(artifact) {
  if (artifact?.content_json) {
    return JSON.stringify(artifact.content_json, null, 2)
  }
  if (artifact?.file_name?.endsWith('.xmind')) {
    return '二进制 XMind 文件，请点击下载。'
  }
  return artifact?.expired_at ? '该产物已按保留策略过期' : '暂无预览'
}
