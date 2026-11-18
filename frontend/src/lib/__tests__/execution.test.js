import { describe, expect, it } from 'vitest'
import { isValidRunId } from '../execution'

describe('execution deep link', () => {
  it('accepts positive numeric route IDs only', () => {
    expect(isValidRunId('123')).toBe(true)
    for (const value of ['0', '-1', '12x', '01', '', ['1'], undefined]) {
      expect(isValidRunId(value)).toBe(false)
    }
  })
})
