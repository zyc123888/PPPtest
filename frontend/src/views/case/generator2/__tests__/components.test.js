import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import GeneratorConfigForm from '../components/GeneratorConfigForm.vue'
import GateIssuesPanel from '../components/GateIssuesPanel.vue'
import JobDetailPanel from '../components/JobDetailPanel.vue'
import MetricsPanel from '../components/MetricsPanel.vue'

function generatorForm(strategy) {
  return {
    project_id: 1,
    name: '测试任务',
    pipeline_mode: 'trusted',
    trusted_generation_strategy: strategy,
    generation_density: 'balanced',
    source_type: 'PASTE',
    markdown_text: '# 需求',
    source_url: '',
    export_xmind: true
  }
}

const modelConfig = {
  name: '默认配置',
  api_key: '',
  model: 'gpt-5.5',
  base_url: ''
}

describe('generator2 component boundaries', () => {
  it('shows generation density only for the source shard strategy', () => {
    const sourceShard = shallowMount(GeneratorConfigForm, {
      props: { form: generatorForm('source_shard'), modelConfig },
      global: { renderStubDefaultSlot: true }
    })
    const liteReview = shallowMount(GeneratorConfigForm, {
      props: { form: generatorForm('lite_review'), modelConfig },
      global: { renderStubDefaultSlot: true }
    })

    expect(sourceShard.find('.generation-density-group').exists()).toBe(true)
    expect(liteReview.find('.generation-density-group').exists()).toBe(false)
  })

  it('passes metrics to the detail child and forwards gate rerun events', async () => {
    const generationMetrics = { testcase_count: 12 }
    const gateIssues = [{ key: 'testcase_handoff', sourceIds: ['SRC-001'], issues: [] }]
    const wrapper = shallowMount(JobDetailPanel, {
      props: {
        job: { id: 17, status: 'FAILED', input_payload_json: {} },
        trusted: true,
        generationMetrics,
        gateIssues
      },
      global: { renderStubDefaultSlot: true }
    })

    expect(wrapper.findComponent(MetricsPanel).props('generationMetrics')).toEqual(generationMetrics)
    wrapper.findComponent(GateIssuesPanel).vm.$emit('rerun-source', { source_id: 'SRC-001' })
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('rerun-source')).toEqual([[{ source_id: 'SRC-001' }]])
  })
})
