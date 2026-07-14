export const MAX_REQUIREMENT_FILE_BYTES = 10 * 1024 * 1024

const ACCEPTED_REQUIREMENT_EXTENSIONS = ['.md', '.markdown', '.txt']
const ACCEPTED_REQUIREMENT_MIME_TYPES = new Set(['', 'text/plain', 'text/markdown', 'text/x-markdown'])

export function validateRequirementFile(file) {
  if (!file) return '未选择文件'
  const name = String(file.name || '').toLowerCase()
  if (!ACCEPTED_REQUIREMENT_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return '仅支持 .md、.markdown 或 .txt 文档'
  }
  if (!ACCEPTED_REQUIREMENT_MIME_TYPES.has(String(file.type || '').toLowerCase())) {
    return `文件类型不受支持：${file.type || 'unknown'}`
  }
  if (Number(file.size || 0) > MAX_REQUIREMENT_FILE_BYTES) {
    return '需求文档不能超过 10 MB'
  }
  return ''
}

export function normalizeModelOptions(items) {
  return (Array.isArray(items) ? items : [])
    .filter((item) => item && item.value && item.label)
    .map((item) => ({
      provider: item.provider || 'Custom',
      label: item.label,
      value: item.value,
      baseUrl: item.base_url || item.baseUrl || ''
    }))
}

export function nextPollingDelay(currentDelay, failed = false) {
  const value = Number(currentDelay) || 3000
  return Math.min(failed ? 20000 : 15000, Math.round(value * (failed ? 1.8 : 1.35)))
}

export function normalizePipelineMode(mode) {
  return mode === 'trusted' || mode === 'trusted_v2' ? 'trusted' : 'lite'
}

export function pipelineModeLabel(mode) {
  return normalizePipelineMode(mode) === 'trusted' ? '可信模式' : '轻量模式'
}

export function formatRate(value) {
  if (value === null || value === undefined || value === '') return '--'
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return '--'
  return `${Math.round(numberValue * 100)}%`
}
