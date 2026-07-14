import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CaseGenerationModeBadge from '@/components/CaseGenerationModeBadge.vue'

const stubs = {
  'el-tag': { template: '<span><slot /></span>' }
}

describe('CaseGenerationModeBadge', () => {
  it.each([
    ['clone', '轻量模式'],
    ['lite', '轻量模式'],
    ['trusted_v2', '可信模式'],
    ['trusted', '可信模式']
  ])('renders %s as %s', (mode, expected) => {
    const wrapper = mount(CaseGenerationModeBadge, { props: { mode }, global: { stubs } })
    expect(wrapper.text()).toBe(expected)
  })
})
