import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AICaseComposer from '../components/AICaseComposer.vue'

const DialogStub = defineComponent({
  setup(_, { slots }) {
    return () => h('div', [slots.default?.(), slots.footer?.()])
  }
})
const ButtonStub = defineComponent({
  props: ['disabled'],
  setup(props, { attrs, slots }) {
    return () => h('button', { ...attrs, disabled: props.disabled }, slots.default?.())
  }
})

describe('AI case saved state', () => {
  it('keeps the saved case visible and offers retry without reopening creation', async () => {
    const wrapper = mount(AICaseComposer, {
      props: {
        modelValue: true,
        form: {},
        draftReady: true,
        draft: { name: '测试用例', target_url: 'http://example.test', steps: [], assertions: [] },
        savedCaseId: 42,
        runError: '执行服务不可用'
      },
      global: { stubs: { ElDialog: DialogStub, ElButton: ButtonStub, ElIcon: true, ElTag: true } }
    })
    expect(wrapper.text()).toContain('用例已创建（#42）')
    expect(wrapper.text()).toContain('执行服务不可用')
    const buttons = wrapper.findAll('button')
    expect(buttons.find((button) => button.text() === '返回修改').attributes('disabled')).toBeDefined()
    expect(buttons.some((button) => button.text() === '高级编辑')).toBe(false)
    await buttons.find((button) => button.text() === '重试运行').trigger('click')
    expect(wrapper.emitted('save-run')).toEqual([[]])
  })
})
