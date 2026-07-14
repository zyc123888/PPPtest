import { describe, expect, it } from 'vitest'
import {
  createUiAssertion,
  createUiStep,
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
      '步骤 1 缺少选择器',
      '断言 1 缺少期望值'
    ])
  })

  it('serializes optional assertion selectors without empty keys', () => {
    const assertion = { ...createUiAssertion('text_visible'), value: '欢迎' }
    expect(serializeUiAssertions([assertion])).toEqual([{ type: 'text_visible', value: '欢迎' }])
  })
})
