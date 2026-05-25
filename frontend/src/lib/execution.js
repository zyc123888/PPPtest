export const EXECUTION_ERROR_TYPE_OPTIONS = [
  { label: '预检失败', value: 'CONFIG', tagType: 'warning' },
  { label: '断言失败', value: 'ASSERTION', tagType: 'danger' },
  { label: '系统异常', value: 'SYSTEM', tagType: 'danger' },
  { label: '超时', value: 'TIMEOUT', tagType: 'danger' },
  { label: '已取消', value: 'CANCELLED', tagType: 'info' }
]

const EXECUTION_STATUS_MAP = {
  healthy: { label: '正常', tagType: 'success' },
  degraded: { label: '降级', tagType: 'warning' },
  unhealthy: { label: '异常', tagType: 'info' },
  loading: { label: '加载中', tagType: 'warning' },
  PENDING: { label: '排队中', tagType: 'warning' },
  RUNNING: { label: '执行中', tagType: 'warning' },
  SUCCESS: { label: '成功', tagType: 'success' },
  FAILED: { label: '失败', tagType: 'danger' },
  ERROR: { label: '异常', tagType: 'info' },
  TIMEOUT: { label: '超时', tagType: 'info' },
  CANCELLED: { label: '取消', tagType: 'info' }
}

const EXECUTION_ERROR_TYPE_MAP = EXECUTION_ERROR_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item
  return acc
}, {})

export const executionStatusText = (status) => {
  return EXECUTION_STATUS_MAP[status]?.label || status
}

export const executionStatusTag = (status) => {
  return EXECUTION_STATUS_MAP[status]?.tagType || 'info'
}

export const executionErrorTypeText = (errorType) => {
  return EXECUTION_ERROR_TYPE_MAP[errorType]?.label || errorType || '-'
}

export const executionErrorTypeTag = (errorType) => {
  return EXECUTION_ERROR_TYPE_MAP[errorType]?.tagType || ''
}
