import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import KanbanBoard from '../components/KanbanBoard.vue'
import {
  DEFECT_COLUMNS,
  DEFECT_STATUS_LABELS,
  REQUIREMENT_COLUMNS,
  REQUIREMENT_STATUS_LABELS
} from '../constants'

function coveredStatuses(columns) {
  return new Set(columns.flatMap((column) => column.statuses || [column.key]))
}

describe('workspace kanban status coverage', () => {
  it('assigns every defect status to a visible column', () => {
    const covered = coveredStatuses(DEFECT_COLUMNS)
    expect(Object.keys(DEFECT_STATUS_LABELS).filter((status) => !covered.has(status))).toEqual([])
    expect(DEFECT_COLUMNS.find((column) => column.key === 'CLOSED').statuses).toContain('WONTFIX')
    expect(DEFECT_COLUMNS.find((column) => column.key === 'REOPENED')).toBeTruthy()
  })

  it('assigns every requirement status to a visible column', () => {
    const covered = coveredStatuses(REQUIREMENT_COLUMNS)
    expect(Object.keys(REQUIREMENT_STATUS_LABELS).filter((status) => !covered.has(status))).toEqual([])
  })

  it('renders unknown statuses and maps archive drops to CLOSED', async () => {
    const items = [
      { id: 1, title: '待处理缺陷', status: 'NEW' },
      { id: 2, title: '暂未知状态', status: 'FUTURE_STATUS' },
      { id: 3, title: '不予处理缺陷', status: 'WONTFIX' }
    ]
    const wrapper = mount(KanbanBoard, { props: { columns: DEFECT_COLUMNS, items }, global: { stubs: { ElTag: true } } })
    const columns = wrapper.findAll('.kanban-col')
    expect(wrapper.findAll('.kanban-card')).toHaveLength(items.length)
    expect(columns.find((column) => column.text().includes('待归类')).text()).toContain('暂未知状态')
    const archive = columns.find((column) => column.find('.kanban-col__head').text().includes('已归档'))
    expect(archive.text()).toContain('不予处理缺陷')
    expect(archive.find('button').attributes('aria-expanded')).toBe('false')
    await archive.find('button').trigger('click')
    expect(archive.find('button').attributes('aria-expanded')).toBe('true')
    await columns.find((column) => column.text().includes('新建')).find('.kanban-card').trigger('dragstart')
    await archive.trigger('drop')
    expect(wrapper.emitted('move')[0][0]).toMatchObject({ fromStatus: 'NEW', toStatus: 'CLOSED' })
  })

  it('supports keyboard open and status move on cards', async () => {
    const items = [{ id: 1, title: '待处理缺陷', status: 'NEW' }]
    const wrapper = mount(KanbanBoard, { props: { columns: DEFECT_COLUMNS, items }, global: { stubs: { ElTag: true } } })
    const card = wrapper.find('.kanban-card')
    expect(card.attributes('tabindex')).toBe('0')
    await card.trigger('keydown.enter')
    expect(wrapper.emitted('open')).toHaveLength(1)
    const select = card.find('select.kanban-card__move')
    expect(select.exists()).toBe(true)
    await select.setValue('CONFIRMED')
    expect(wrapper.emitted('move')[0][0]).toMatchObject({ fromStatus: 'NEW', toStatus: 'CONFIRMED' })
  })
})
