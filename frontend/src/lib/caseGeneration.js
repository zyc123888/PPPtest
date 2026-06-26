import { api } from '@/lib/api'

export function listCaseGenerationJobs(options = {}) {
  const projectId = options.projectId ?? null
  const query = projectId ? `?project_id=${projectId}` : ''
  return api.get(`/case-generation/jobs${query}`)
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

export function caseGenerationStatusTagType(status) {
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'info'
  if (status === 'RUNNING') return 'warning'
  return 'info'
}

const ARTIFACT_LABELS = { xmind: 'XMind', xmind_export_log: 'XMind Log' }

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
  return artifact?.file_path || '暂无预览'
}
