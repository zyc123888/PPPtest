import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CaseTable from '../components/CaseTable.vue'

const row = {
  id: 17,
  name: '状态展示用例',
  project_id: 1,
  priority: 'P2',
  status: 'ACTIVE',
  review_status: 'DRAFT',
  target_url: 'http://example.test',
  steps_json: []
}

const TableStub = defineComponent({
  setup(_, { slots }) {
    return () => h('div', { class: 'table-stub' }, slots.default?.())
  }
})

const TableColumnStub = defineComponent({
  props: ['label'],
  setup(props, { slots }) {
    return () => h('div', { class: 'column-stub', 'data-label': props.label }, slots.default?.({ row }) || [])
  }
})

const ButtonStub = defineComponent({
  setup(_, { attrs, slots }) {
    return () => h('button', attrs, slots.default?.())
  }
})

describe('UI case latest run state', () => {
  it('shows unknown instead of not-run and offers retry after a load failure', async () => {
    const wrapper = mount(CaseTable, {
      props: {
        rows: [row],
        latestRunMap: {},
        latestRunState: 'error',
        projectMap: {}
      },
      global: {
        stubs: {
          ElTable: TableStub,
          ElTableColumn: TableColumnStub,
          ElButton: ButtonStub,
          ElTooltip: true,
          ElTag: true,
          ElPagination: true
        },
        directives: { loading: vi.fn() }
      }
    })

    const latestRunCell = wrapper.find('[data-label="最近执行"]')
    expect(latestRunCell.text()).toContain('状态未知')
    expect(latestRunCell.text()).not.toContain('未执行')
    await latestRunCell.get('button').trigger('click')
    expect(wrapper.emitted('retry-latest-runs')).toEqual([[]])
  })
})
