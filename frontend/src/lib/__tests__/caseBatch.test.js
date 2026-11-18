import { describe, expect, it } from 'vitest'
import { buildCaseBatchPatch } from '../caseBatch'

describe('buildCaseBatchPatch', () => {
  it('distinguishes keep, set and clear operations', () => {
    expect(buildCaseBatchPatch({ folder_mode: 'keep' })).toEqual({})
    expect(buildCaseBatchPatch({ folder_mode: 'set', folder_path: '登录/异常' })).toEqual({ folder_path: '登录/异常' })
    expect(buildCaseBatchPatch({ folder_mode: 'clear' })).toEqual({ folder_path: null })
    expect(buildCaseBatchPatch({ tags_mode: 'clear' })).toEqual({ tags_json: null })
    expect(buildCaseBatchPatch({ tags_mode: 'keep', tags_json: ['旧标签'] })).toEqual({})
    expect(buildCaseBatchPatch({ tags_mode: 'set', tags_json: ['冒烟'] })).toEqual({ tags_json: ['冒烟'] })
  })
})
