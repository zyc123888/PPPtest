import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AICaseComposer from '../components/AICaseComposer.vue'

const DialogStub = defineComponent({
  setup(_, { slots }) {
    return () => h('div', [slots.header?.(), slots.default?.(), slots.footer?.()])
  }
})
const ButtonStub = defineComponent({
  props: ['disabled'],
  setup(props, { attrs, slots }) {
    return () => h('button', { ...attrs, disabled: props.disabled }, slots.default?.())
  }
})
const TagStub = defineComponent({
  setup(_, { slots }) {
    return () => h('span', { class: 'el-tag-stub' }, slots.default?.())
  }
})

const mountComposer = (extraProps = {}) => mount(AICaseComposer, {
  props: {
    modelValue: true,
    form: {},
    draftReady: true,
    draft: { name: '测试用例', target_url: 'http://example.test', steps: [], assertions: [], expect_text: '欢迎语' },
    warnings: [],
    ...extraProps
  },
  global: { stubs: { ElDialog: DialogStub, ElButton: ButtonStub, ElIcon: true, ElTag: TagStub } }
})

describe('AICaseComposer 草稿元数据与告警展示', () => {
  it('Skill 版本读取 draft 元数据并展示实际版本号', () => {
    const wrapper = mountComposer({
      draft: { name: '测试用例', target_url: 'http://example.test', steps: [], assertions: [], skill_name: 'ui-case-designer', skill_version: '3.1.0' }
    })
    expect(wrapper.find('.el-tag-stub').text()).toBe('ui-case-designer · v3.1.0')
  })

  it('取不到 Skill 版本时不显示版本标签', () => {
    const wrapper = mountComposer()
    expect(wrapper.text()).not.toContain('· v')
  })

  it('警告条显示总数，默认只展示第一条，可展开全部并收起', async () => {
    const warnings = ['缺少验证码输入步骤', '目标地址非生产环境', '第 3 步断言较宽松']
    const wrapper = mountComposer({ warnings })
    expect(wrapper.text()).toContain('共 3 项需要留意')
    expect(wrapper.text()).toContain(warnings[0])
    expect(wrapper.text()).not.toContain(warnings[1])

    const toggle = wrapper.find('.draft-notice__toggle')
    expect(toggle.text()).toContain('展开全部 3 项')
    await toggle.trigger('click')
    expect(wrapper.text()).toContain(warnings[1])
    expect(wrapper.text()).toContain(warnings[2])
    expect(wrapper.find('.draft-notice__toggle').text()).toContain('收起')

    await wrapper.find('.draft-notice__toggle').trigger('click')
    expect(wrapper.text()).not.toContain(warnings[1])
  })

  it('单条警告不出现展开按钮', () => {
    const wrapper = mountComposer({ warnings: ['仅一条提示'] })
    expect(wrapper.text()).toContain('共 1 项需要留意')
    expect(wrapper.find('.draft-notice__toggle').exists()).toBe(false)
  })

  it('通过条件项展示中性「待验证」标注而非通过态', () => {
    const wrapper = mountComposer({
      draft: { name: '测试用例', target_url: 'http://example.test', expect_text: '欢迎语', steps: [], assertions: [{ type: 'assert_text', value: '登录成功' }] }
    })
    const items = wrapper.findAll('.assertion-item')
    expect(items.length).toBe(2)
    expect(items[0].text()).toContain('页面显示“欢迎语”')
    expect(items[0].text()).toContain('待验证')
    expect(items[1].text()).toContain('登录成功')
    expect(items[1].text()).toContain('待验证')
    expect(wrapper.html()).not.toContain('circle-check')
  })
})
