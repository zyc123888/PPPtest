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
})
