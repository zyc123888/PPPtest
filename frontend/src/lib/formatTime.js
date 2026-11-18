// 统一时间口径：后端返回的无时区（naive）时间字符串按 UTC 解析（补 'Z'），再以本地时区展示。
// 口径基准取自 layout/components/Header.vue 的 formatTokenTime 原有实现。

const TZ_SUFFIX_RE = /(Z|[+-]\d{2}:?\d{2})$/

function normalizeTime(value) {
  if (value instanceof Date) return value
  const str = String(value ?? '')
  if (!str) return ''
  return TZ_SUFFIX_RE.test(str) ? str : `${str}Z`
}

export function formatDateTime(value, fallback = '-') {
  if (!value) return fallback
  const date = new Date(normalizeTime(value))
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatShortTime(value, fallback = '-') {
  if (!value) return fallback
  const date = new Date(normalizeTime(value))
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
