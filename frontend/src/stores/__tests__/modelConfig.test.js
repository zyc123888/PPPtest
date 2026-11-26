import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/lib/caseGeneration', () => ({
  getCaseGenerationModelConfig: vi.fn(),
  listCaseGenerationModelOptions: vi.fn(),
  saveCaseGenerationModelConfig: vi.fn()
}))

import {
  getCaseGenerationModelConfig,
  listCaseGenerationModelOptions,
  saveCaseGenerationModelConfig
} from '@/lib/caseGeneration'
import { useModelConfigStore } from '../modelConfig'

describe('useModelConfigStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('deduplicates model options and workspace config fetches and updates cache on save', async () => {
    listCaseGenerationModelOptions.mockResolvedValueOnce([{ value: 'gpt-5.5', provider: 'OPENAI' }])
    getCaseGenerationModelConfig.mockResolvedValueOnce({
      workspace_id: 5,
      model: 'gpt-5.5',
      base_url: 'https://api.openai.com/v1',
      name: '默认'
    })

    const store = useModelConfigStore()
    const [opt1, opt2] = await Promise.all([store.fetchModelOptions(), store.fetchModelOptions()])
    expect(opt1).toHaveLength(1)
    expect(opt2).toHaveLength(1)
    expect(listCaseGenerationModelOptions).toHaveBeenCalledTimes(1)

    const cfg = await store.fetchWorkspaceConfig(5)
    expect(cfg.model).toBe('gpt-5.5')
    await store.fetchWorkspaceConfig(5)
    expect(getCaseGenerationModelConfig).toHaveBeenCalledTimes(1)

    saveCaseGenerationModelConfig.mockResolvedValueOnce({
      workspace_id: 5,
      model: 'qwen-max',
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      name: '通义'
    })
    await store.saveWorkspaceConfig({ workspace_id: 5, model: 'qwen-max', api_key: 'sk-123' })
    const cached = await store.fetchWorkspaceConfig(5)
    expect(cached.model).toBe('qwen-max')
    expect(getCaseGenerationModelConfig).toHaveBeenCalledTimes(1)
  })
})
