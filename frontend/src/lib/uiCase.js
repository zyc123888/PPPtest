export const UI_STEP_OPTIONS = [
  { value: 'click', label: '点击元素', selector: true },
  { value: 'fill', label: '填写内容', selector: true, needsValue: true, valueLabel: '填写值' },
  { value: 'press', label: '按键', selector: true, needsValue: true, valueLabel: '按键名称' },
  { value: 'select_option', label: '选择下拉项', selector: true, needsValue: true, valueLabel: '选项值' },
  { value: 'check', label: '勾选', selector: true },
  { value: 'uncheck', label: '取消勾选', selector: true },
  { value: 'hover', label: '悬停', selector: true },
  { value: 'wait_for_selector', label: '等待元素', selector: true, state: true },
  { value: 'wait_for_text', label: '等待文本', needsValue: true, optionalSelector: true, valueLabel: '文本' },
  { value: 'wait', label: '固定等待', duration: true },
  { value: 'goto', label: '打开页面', needsValue: true, valueLabel: '页面地址', waitUntil: true },
  { value: 'set_viewport', label: '设置视口', viewport: true },
  { value: 'assert_text', label: '断言文本', needsValue: true, optionalSelector: true, valueLabel: '期望文本' },
  { value: 'assert_visible', label: '断言元素可见', selector: true },
  { value: 'assert_hidden', label: '断言元素隐藏', selector: true },
  { value: 'assert_url_contains', label: '断言地址包含', needsValue: true, valueLabel: '地址片段' },
  { value: 'assert_title_contains', label: '断言标题包含', needsValue: true, valueLabel: '标题片段' }
]

export const UI_ASSERTION_OPTIONS = [
  { value: 'text_visible', label: '文本可见', needsValue: true, optionalSelector: true, valueLabel: '期望文本' },
  { value: 'text_hidden', label: '文本隐藏', needsValue: true, optionalSelector: true, valueLabel: '期望文本' },
  { value: 'selector_visible', label: '元素可见', selector: true },
  { value: 'selector_hidden', label: '元素隐藏', selector: true },
  { value: 'url_contains', label: '地址包含', needsValue: true, valueLabel: '地址片段' },
  { value: 'title_contains', label: '标题包含', needsValue: true, valueLabel: '标题片段' }
]

const stepMap = new Map(UI_STEP_OPTIONS.map((item) => [item.value, item]))
const assertionMap = new Map(UI_ASSERTION_OPTIONS.map((item) => [item.value, item]))

export const getStepDefinition = (action) => stepMap.get(action) || UI_STEP_OPTIONS[0]
export const getAssertionDefinition = (type) => assertionMap.get(type) || UI_ASSERTION_OPTIONS[0]

export const createUiStep = (action = 'click') => ({
  action,
  name: '',
  selector: '',
  value: '',
  duration_ms: 1000,
  state: 'visible',
  wait_until: 'domcontentloaded',
  width: 1440,
  height: 900
})

export const createUiAssertion = (type = 'text_visible') => ({
  type,
  name: '',
  selector: '',
  value: ''
})

const compact = (value) => {
  if (Array.isArray(value)) return value.map(compact)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key, item]) => !key.startsWith('_') && item !== '' && item !== null && item !== undefined)
      .map(([key, item]) => [key, compact(item)])
  )
}

export const normalizeUiStep = (step = {}) => ({ ...createUiStep(step.action), ...step })

export const normalizeUiAssertion = (assertion = {}) => {
  const normalizedType = assertion.type === 'text_present' ? 'text_visible' : assertion.type
  return {
    ...createUiAssertion(normalizedType),
    ...assertion,
    type: normalizedType,
    value: assertion.value ?? assertion.expected ?? ''
  }
}

export const serializeUiSteps = (steps = []) => steps.map((step) => {
  const definition = getStepDefinition(step.action)
  const payload = { action: step.action }
  if (step.name?.trim()) payload.name = step.name.trim()
  if (definition.selector || definition.optionalSelector) payload.selector = step.selector?.trim() || undefined
  if (definition.needsValue) payload.value = step.value
  if (definition.duration) payload.duration_ms = Number(step.duration_ms)
  if (definition.state) payload.state = step.state
  if (definition.waitUntil) payload.wait_until = step.wait_until
  if (definition.viewport) {
    payload.width = Number(step.width)
    payload.height = Number(step.height)
  }
  return compact(payload)
})

export const serializeUiAssertions = (assertions = []) => assertions.map((assertion) => {
  const definition = getAssertionDefinition(assertion.type)
  const payload = { type: assertion.type }
  if (assertion.name?.trim()) payload.name = assertion.name.trim()
  if (definition.selector || definition.optionalSelector) payload.selector = assertion.selector?.trim() || undefined
  if (definition.needsValue) payload.value = assertion.value
  return compact(payload)
})

export const validateUiWorkflow = (steps = [], assertions = []) => {
  const errors = []
  steps.forEach((step, index) => {
    const definition = getStepDefinition(step.action)
    if (definition.selector && !step.selector?.trim()) errors.push(`步骤 ${index + 1} 缺少选择器`)
    if (definition.needsValue && String(step.value ?? '').trim() === '') errors.push(`步骤 ${index + 1} 缺少值`)
    if (definition.duration && !(Number(step.duration_ms) >= 1 && Number(step.duration_ms) <= 60000)) {
      errors.push(`步骤 ${index + 1} 的等待时间应为 1 到 60000 毫秒`)
    }
  })
  assertions.forEach((assertion, index) => {
    const definition = getAssertionDefinition(assertion.type)
    if (definition.selector && !assertion.selector?.trim()) errors.push(`断言 ${index + 1} 缺少选择器`)
    if (definition.needsValue && !String(assertion.value ?? '').trim()) errors.push(`断言 ${index + 1} 缺少期望值`)
  })
  return errors
}
