import { describe, expect, it } from 'vitest'
import { formatDebugBody, parseQueryParamsFromPath } from '../apiCaseUtils'

describe('apiCaseUtils', () => {
  it('formats debug response body cleanly', () => {
    expect(formatDebugBody(null)).toBe('')
    expect(formatDebugBody('plain text')).toBe('plain text')
    expect(formatDebugBody({ ok: true, count: 2 })).toBe('{\n  "ok": true,\n  "count": 2\n}')
  })

  it('parses query params from API path', () => {
    expect(parseQueryParamsFromPath('/api/v1/users')).toEqual([])
    expect(parseQueryParamsFromPath('/api/v1/users?page=2&keyword=hello%20world')).toEqual([
      { enabled: true, key: 'page', value: '2' },
      { enabled: true, key: 'keyword', value: 'hello world' }
    ])
  })
})
