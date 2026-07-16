import { describe, expect, it } from 'vitest'

import {
  buildTrustedGateIssues,
  canRerunSourceShard,
  filterVisibleArtifacts,
  filterStageArtifacts,
  formatDurationMs,
  formatJobListSummary,
  formatRecoveryPlan,
  formatScopeIndexStrategy,
  generationDensityLabel,
  hasSourceGap,
  jobPipelineMode,
  resolveFinalDeliveryGatePassed,
  sourceStatusTag,
  trustedGenerationStrategyLabel
} from '../presentation'

const stageLabels = {
  scope_index: '索引',
  testcase_by_source_shard: '用例基线'
}

describe('generator2 presentation contracts', () => {
  it('keeps current and historical job mode payloads intact', () => {
    expect(jobPipelineMode({ input_payload_json: { pipeline_mode: 'clone' } })).toBe('clone')
    expect(jobPipelineMode({ input_payload_json: { pipeline_mode: 'trusted_v2' } })).toBe('trusted_v2')
    expect(jobPipelineMode({})).toBe('lite')
  })

  it('keeps generation option labels stable', () => {
    expect(trustedGenerationStrategyLabel('lite_review')).toBe('轻量结果审查')
    expect(trustedGenerationStrategyLabel('source_shard')).toBe('按 source 分片')
    expect(generationDensityLabel('exhaustive')).toBe('全面')
    expect(generationDensityLabel('unknown')).toBe('均衡')
  })

  it('shortens generated summaries without losing outcome and advice count', () => {
    expect(formatJobListSummary({
      summary: '已生成 155 条用例并导出 XMind（有条件通过，20 项改进建议）'
    })).toBe('155 条用例 · 条件通过 · 20 项建议')
    expect(formatJobListSummary({ summary: '正在执行范围索引' })).toBe('正在执行范围索引')
    expect(formatJobListSummary({})).toBe('暂无摘要')
  })

  it('formats the scope strategy with batching and concurrency evidence', () => {
    expect(formatScopeIndexStrategy({
      mode: 'section_batches_lightweight',
      section_count: 18,
      batch_count: 3,
      concurrency: 2,
      uses_lightweight_discovery: true
    })).toBe('长文档轻量索引 · 18 章节 · 3 批 · 并发 2 · 轻量识别')
  })

  it('normalizes gate issues, recovery actions and source rerun scope', () => {
    const gates = buildTrustedGateIssues([
      {
        artifact_type: 'testcase_handoff',
        content_json: {
          testcase_gate: {
            issues: [
              { severity: 'blocker', code: 'FP_MISSING', message: 'FP-001 未消费' },
              { severity: 'warning', code: 'WEAK_EXPECTED', message: '弱预期' }
            ],
            issue_counts: { blocker: 1, warning: 1 },
            recovery_plan: {
              strategy: 'local_rerun',
              return_to: 'testcase_by_source_shard',
              rerun_scope: { source_ids: ['SRC-001', 'SRC-002'] }
            }
          }
        }
      }
    ], stageLabels)

    expect(gates).toHaveLength(1)
    expect(gates[0]).toMatchObject({
      key: 'testcase_handoff',
      label: '用例门禁',
      tagType: 'danger',
      statusText: '1 项阻断',
      sourceIds: ['SRC-001', 'SRC-002'],
      canRerunStage: false
    })
    expect(gates[0].recoveryText).toBe('局部重跑 / 退回 用例基线 / 影响 SRC-001、SRC-002')
  })

  it('marks stage reruns only for blocking stage-level recovery', () => {
    const gates = buildTrustedGateIssues([
      {
        artifact_type: 'scope_index_gate',
        content_json: {
          scope_index_gate: {
            issues: [{ severity: 'blocker', message: '索引不完整' }],
            recovery_plan: { strategy: 'stage_rerun', return_to: 'scope_index' }
          }
        }
      }
    ], stageLabels)

    expect(gates[0].canRerunStage).toBe(true)
    expect(gates[0].recoveryText).toBe('阶段重跑 / 退回 索引')
    expect(formatRecoveryPlan({ strategy: 'none' }, stageLabels)).toBe('')
  })

  it('keeps artifact visibility mode-specific', () => {
    const artifacts = [
      { artifact_type: 'xmind' },
      { artifact_type: 'scope_index' },
      { artifact_type: 'secret_internal' },
      { artifact_type: 'generation_metrics' }
    ]
    expect(filterVisibleArtifacts(artifacts, false).map((item) => item.artifact_type)).toEqual(['xmind', 'generation_metrics'])
    expect(filterVisibleArtifacts(artifacts, true).map((item) => item.artifact_type)).toEqual(['xmind', 'scope_index', 'generation_metrics'])
  })

  it('places trusted artifacts under their owning progress stage', () => {
    const artifacts = [
      { artifact_type: 'source_manifest' },
      { artifact_type: 'scope_index' },
      { artifact_type: 'scope_index_gate' },
      { artifact_type: 'xmind' }
    ]

    expect(filterStageArtifacts(artifacts, 'scope_index', true).map((item) => item.artifact_type)).toEqual([
      'source_manifest',
      'scope_index'
    ])
    expect(filterStageArtifacts(artifacts, 'scope_index_gate', true).map((item) => item.artifact_type)).toEqual([
      'scope_index_gate'
    ])
    expect(filterStageArtifacts(artifacts, 'export', true)).toEqual([])
  })

  it('prefers the delivery artifact result and falls back to review metrics', () => {
    expect(resolveFinalDeliveryGatePassed({ content_json: { passed: false } }, { final_delivery_gate_passed: true })).toBe(false)
    expect(resolveFinalDeliveryGatePassed(null, { final_delivery_gate_passed: true })).toBe(true)
    expect(resolveFinalDeliveryGatePassed(null, {})).toBeNull()
  })

  it('classifies source coverage gaps consistently', () => {
    expect(hasSourceGap({ must_cover_status: 'gap', method_consumption_status: 'covered' })).toBe(true)
    expect(hasSourceGap({ must_cover_status: 'covered', method_consumption_status: 'pass' })).toBe(false)
    expect(sourceStatusTag('blocked')).toBe('warning')
    expect(sourceStatusTag('ok')).toBe('success')
    expect(sourceStatusTag('unknown')).toBe('info')
  })

  it('allows source reruns only for finished trusted jobs with actionable gaps', () => {
    const failedSource = { source_id: 'SRC-001', shard_status: 'failed' }
    expect(canRerunSourceShard({ status: 'FAILED' }, true, failedSource)).toBe(true)
    expect(canRerunSourceShard({ status: 'SUCCESS' }, true, { source_id: 'SRC-002', must_cover_status: 'gap' })).toBe(true)
    expect(canRerunSourceShard({ status: 'RUNNING' }, true, failedSource)).toBe(false)
    expect(canRerunSourceShard({ status: 'SUCCESS' }, false, failedSource)).toBe(false)
  })

  it('formats stage durations consistently across seconds, minutes and hours', () => {
    expect(formatDurationMs(999)).toBe('1s')
    expect(formatDurationMs(65_000)).toBe('1m 5s')
    expect(formatDurationMs(3_665_000)).toBe('1h 1m 5s')
    expect(formatDurationMs(0)).toBe('')
  })
})
