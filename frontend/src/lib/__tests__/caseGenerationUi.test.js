import { describe, expect, it } from 'vitest'

import {
  formatRate,
  nextPollingDelay,
  normalizeModelOptions,
  normalizePipelineMode,
  pipelineModeLabel,
  validateRequirementFile
} from '@/lib/caseGenerationUi'

describe('case-generation UI contracts', () => {
  it('keeps legacy and current pipeline modes compatible', () => {
    expect(normalizePipelineMode('clone')).toBe('lite')
    expect(normalizePipelineMode('trusted_v2')).toBe('trusted')
    expect(pipelineModeLabel('trusted')).toBe('可信模式')
    expect(pipelineModeLabel('clone')).toBe('轻量模式')
  })

  it('distinguishes an unknown rate from a real zero', () => {
    expect(formatRate(null)).toBe('--')
    expect(formatRate(undefined)).toBe('--')
    expect(formatRate(0)).toBe('0%')
    expect(formatRate(0.875)).toBe('88%')
  })

  it('backs polling off within explicit bounds', () => {
    expect(nextPollingDelay(3000)).toBe(4050)
    expect(nextPollingDelay(15000)).toBe(15000)
    expect(nextPollingDelay(3000, true)).toBe(5400)
    expect(nextPollingDelay(20000, true)).toBe(20000)
  })

  it('validates requirement file extension, mime and size', () => {
    expect(validateRequirementFile({ name: 'prd.md', type: 'text/markdown', size: 100 })).toBe('')
    expect(validateRequirementFile({ name: 'prd.pdf', type: 'application/pdf', size: 100 })).toContain('仅支持')
    expect(validateRequirementFile({ name: 'prd.md', type: 'application/pdf', size: 100 })).toContain('文件类型')
    expect(validateRequirementFile({ name: 'prd.md', type: 'text/markdown', size: 11 * 1024 * 1024 })).toContain('10 MB')
  })

  it('normalizes backend model registry records', () => {
    expect(normalizeModelOptions([{ provider: 'OpenAI', label: 'GPT', value: 'gpt', base_url: 'https://example.test/v1' }])).toEqual([
      { provider: 'OpenAI', label: 'GPT', value: 'gpt', baseUrl: 'https://example.test/v1' }
    ])
  })
})
