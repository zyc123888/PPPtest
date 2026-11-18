import { describe, expect, it } from 'vitest'
import {
  UI_STEP_OPTIONS,
  createUiAssertion,
  createUiStep,
  findUnsupportedActions,
  getStepOptions,
  hasResetUiInput,
  mergeUiAssertion,
  mergeUiStep,
  normalizeUiAssertion,
  serializeUiAssertions,
  serializeUiSteps,
  validateUiWorkflow
} from '../uiCase'

describe('UI case workflow helpers', () => {
  it('serializes only fields used by the selected action', () => {
    const click = { ...createUiStep('click'), selector: '#submit', value: 'ignored', name: '提交' }
    const wait = { ...createUiStep('wait'), duration_ms: 1500, selector: '#ignored' }

    expect(serializeUiSteps([click, wait])).toEqual([
      { action: 'click', name: '提交', selector: '#submit' },
      { action: 'wait', duration_ms: 1500 }
    ])
  })

  it('normalizes legacy text_present assertions', () => {
    expect(normalizeUiAssertion({ type: 'text_present', expected: '登录' })).toMatchObject({
      type: 'text_visible',
      value: '登录'
    })
  })

  it('validates required selectors and expected values', () => {
    const step = createUiStep('click')
    const assertion = createUiAssertion('url_contains')

    expect(validateUiWorkflow([step], [assertion])).toEqual([
      '步骤 1 缺少语义目标或选择器',
      '断言 1 缺少期望值'
    ])
  })

  it('accepts and serializes semantic targets without selectors', () => {
    const step = {
      ...createUiStep('click'),
      target: '登录按钮',
      role: 'button',
      accessible_name: '登录'
    }

    expect(validateUiWorkflow([step], [])).toEqual([])
    expect(serializeUiSteps([step])).toEqual([
      {
        action: 'click',
        target: '登录按钮',
        role: 'button',
        accessible_name: '登录'
      }
    ])
  })

  it('supports visual assertions', () => {
    const assertion = {
      ...createUiAssertion('visual'),
      target: '登录表单',
      value: '表单完整可见且没有遮挡'
    }
    expect(validateUiWorkflow([], [assertion])).toEqual([])
    expect(serializeUiAssertions([assertion])).toEqual([
      { type: 'visual', target: '登录表单', value: '表单完整可见且没有遮挡' }
    ])
  })

  it('serializes optional assertion selectors without empty keys', () => {
    const assertion = { ...createUiAssertion('text_visible'), value: '欢迎' }
    expect(serializeUiAssertions([assertion])).toEqual([{ type: 'text_visible', value: '欢迎' }])
  })

  it('keeps shared semantic fields when switching actions', () => {
    const step = { ...createUiStep('click'), name: '点击搜索', target: '搜索按钮', selector: '#search' }
    const fill = mergeUiStep(step, 'fill')

    expect(fill).toMatchObject({ action: 'fill', name: '点击搜索', target: '搜索按钮', selector: '#search' })
    expect(fill.value).toBe('')
    expect(mergeUiStep(step, 'wait').selector).toBe('')
  })

  it('detects reset values and options without warning for preserved fields', () => {
    const click = { ...createUiStep('click'), target: '搜索按钮', selector: '#search' }
    expect(hasResetUiInput(click, mergeUiStep(click, 'fill'))).toBe(false)
    expect(hasResetUiInput(click, mergeUiStep(click, 'wait'))).toBe(true)
    const wait = { ...createUiStep('wait'), duration_ms: 2500 }
    expect(hasResetUiInput(wait, mergeUiStep(wait, 'click'))).toBe(true)
    const fill = { ...createUiStep('fill'), value: '示例' }
    expect(hasResetUiInput(fill, mergeUiStep(fill, 'press'))).toBe(true)
  })

  it('keeps assertion names but removes incompatible targets', () => {
    const assertion = { ...createUiAssertion('selector_visible'), name: '结果可见', target: '结果列表' }
    expect(mergeUiAssertion(assertion, 'url_contains')).toMatchObject({ type: 'url_contains', name: '结果可见', target: '' })
  })
})

describe('engine action whitelists', () => {
  it('limits Midscene candidates to actions the runner explicitly supports', () => {
    expect(getStepOptions('midscene').map((item) => item.value)).toEqual([
      'click', 'fill', 'wait', 'goto', 'assert_text'
    ])
  })

  it('keeps native candidates identical to the shared option list', () => {
    expect(getStepOptions('native').map((item) => item.value)).toEqual(UI_STEP_OPTIONS.map((item) => item.value))
    expect(getStepOptions().map((item) => item.value)).toEqual(UI_STEP_OPTIONS.map((item) => item.value))
  })

  it('flags unsupported actions with action name and engine in validation errors', () => {
    const steps = [{ ...createUiStep('hover'), target: '菜单' }, { ...createUiStep('click'), target: '提交' }]
    expect(validateUiWorkflow(steps, [], 'midscene')).toEqual([
      '步骤 1 的动作 hover 不受 Midscene 引擎支持'
    ])
    expect(validateUiWorkflow(steps, [], 'native')).toEqual([])
  })

  it('lists unsupported actions of legacy cases without blocking display', () => {
    expect(findUnsupportedActions([{ action: 'set_viewport' }, { action: 'click' }], 'midscene')).toEqual(['set_viewport'])
    expect(findUnsupportedActions([{ action: 'click' }], 'native')).toEqual([])
    expect(findUnsupportedActions([], 'midscene')).toEqual([])
  })
})
