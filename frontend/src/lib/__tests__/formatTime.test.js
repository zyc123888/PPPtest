import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatDateTime, formatShortTime } from '../formatTime'

describe('formatTime 统一时间口径', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2026-11-13T10:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('无时区（naive UTC）输入与带 Z 输入得到一致的本地展示', () => {
    expect(formatDateTime('2026-06-01 08:00:00')).toBe(formatDateTime('2026-06-01T08:00:00Z'))
    expect(formatDateTime('2026-06-01T08:00:00')).toBe(formatDateTime('2026-06-01T08:00:00Z'))
    expect(formatShortTime('2026-06-01 08:00:00')).toBe(formatShortTime('2026-06-01T08:00:00Z'))
  })

  it('已带时区偏移的输入保持原时刻，不再补 Z', () => {
    expect(formatDateTime('2026-06-01T08:00:00+02:00')).toBe(formatDateTime('2026-06-01T06:00:00Z'))
    expect(formatShortTime('2026-06-01T08:00:00+02:00')).toBe(formatShortTime('2026-06-01T06:00:00Z'))
  })

  it('空值与无效输入返回 fallback', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime(undefined)).toBe('-')
    expect(formatDateTime('not-a-time', '—')).toBe('—')
    expect(formatShortTime('', '')).toBe('')
  })

  it('短格式输出为 月/日 时:分 的本地时区展示', () => {
    expect(formatShortTime('2026-06-01T08:00:00Z')).toMatch(/^\d{2}\/\d{2} \d{2}:\d{2}$/)
  })
})
