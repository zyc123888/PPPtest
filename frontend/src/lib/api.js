// API 基础路径
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const API_PREFIX = `${API_BASE_URL}/v1`
const TOKEN_KEY = 'tp_token'

const FIELD_LABELS = {
  name: '名称',
  description: '说明',
  base_url: '基础地址',
  workspace_id: '所属空间',
  project_id: '所属项目',
  environment_id: '执行环境',
  method: '请求方法',
  path: '请求路径',
  target_url: '目标地址',
  expect_text: '期望文本',
  steps_json: '步骤 JSON',
  headers_json: '请求头 JSON',
  body_json: '请求体 JSON',
  expected_status: '预期状态码',
  variables_json: '变量 JSON',
  payload: '输入内容'
}

function extractFieldName(location) {
  if (!Array.isArray(location) || location.length === 0) return '字段'
  return location[location.length - 1]
}

function translateDetail(detail) {
  const fieldName = extractFieldName(detail?.loc)
  const fieldLabel = FIELD_LABELS[fieldName] || fieldName

  switch (detail?.type) {
    case 'string_too_short':
      return `${fieldLabel}至少需要 ${detail?.ctx?.min_length || 1} 个字符`
    case 'string_too_long':
      return `${fieldLabel}不能超过 ${detail?.ctx?.max_length || 0} 个字符`
    case 'missing':
      return `${fieldLabel}不能为空`
    case 'int_parsing':
      return `${fieldLabel}必须是整数`
    case 'list_type':
      return `${fieldLabel}格式不正确，应为列表`
    case 'dict_type':
      return `${fieldLabel}格式不正确，应为对象`
    default:
      return detail?.msg || '请求参数校验失败'
  }
}

function formatErrorPayload(payload, status) {
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map(translateDetail).join('；')
  }

  if (typeof payload?.detail === 'string' && payload.detail.trim()) {
    return payload.detail
  }

  return `请求失败，状态码 ${status}`
}

async function request(path, options = {}) {
  const token = localStorage.getItem(TOKEN_KEY)
  const isForm = options.body instanceof FormData
  const config = {
    method: options.method || 'GET',
    headers: {
      ...(options.body && !isForm ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {})
    }
  }

  if (options.body) {
    config.body = isForm ? options.body : JSON.stringify(options.body)
  }

  const response = await fetch(`${API_PREFIX}${path}`, config)
  if (!response.ok) {
    const text = await response.text()

    try {
      const payload = text ? JSON.parse(text) : null
      throw new Error(formatErrorPayload(payload, response.status))
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new Error(text || `请求失败，状态码 ${response.status}`)
      }
      throw error
    }
  }

  if (response.status === 204) {
    return null
  }

  if (options.responseType === 'blob') {
    return response.blob()
  }

  if (options.responseType === 'text') {
    return response.text()
  }

  const text = await response.text()
  if (!text) return null
  return JSON.parse(text)
}

export const api = {
  get(path) {
    return request(path)
  },
  getBlob(path) {
    return request(path, { responseType: 'blob' })
  },
  post(path, body) {
    if (body === undefined) {
      return request(path, { method: 'POST' })
    }
    return request(path, { method: 'POST', body })
  },
  postForm(path, formData) {
    return request(path, { method: 'POST', body: formData })
  },
  delete(path, body) {
    if (body === undefined) {
      return request(path, { method: 'DELETE' })
    }
    return request(path, { method: 'DELETE', body })
  },
  put(path, body) {
    return request(path, { method: 'PUT', body })
  }
}
