import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn()
  },
  isAbortError: (err) => err?.name === 'AbortError'
}))

import { api } from '@/lib/api'
import { useExecutionStream } from '../useExecutionStream'

describe('useExecutionStream', () => {
  const OriginalEventSource = globalThis.EventSource
  let instances

  beforeEach(() => {
    vi.useFakeTimers()
    instances = []
    globalThis.EventSource = class MockEventSource {
      constructor(url, options) {
        this.url = url
        this.options = options
        this.closed = false
        this.onopen = null
        this.onmessage = null
        this.onerror = null
        instances.push(this)
      }
      close() {
        this.closed = true
      }
    }
    vi.clearAllMocks()
  })

  afterEach(() => {
    globalThis.EventSource = OriginalEventSource
    vi.useRealTimers()
  })

  it('receives SSE updates and closes automatically upon terminal status', () => {
    const onMessage = vi.fn()
    const onTerminal = vi.fn()

    const scope = effectScope()
    const stream = scope.run(() => useExecutionStream())
    stream.subscribe(42, { onMessage, onTerminal })

    expect(instances).toHaveLength(1)
    expect(instances[0].url).toContain('/executions/runs/42/stream')
    instances[0].onopen?.()
    expect(stream.mode.value).toBe('sse')

    instances[0].onmessage({ data: JSON.stringify({ id: 42, status: 'RUNNING', summary: '执行中' }) })
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ status: 'RUNNING' }), 42)
    expect(instances[0].closed).toBe(false)

    instances[0].onmessage({ data: JSON.stringify({ id: 42, status: 'SUCCESS', summary: '完成' }) })
    expect(onTerminal).toHaveBeenCalledWith(expect.objectContaining({ status: 'SUCCESS' }), 42)
    expect(instances[0].closed).toBe(true)
    expect(stream.mode.value).toBe('closed')

    scope.stop()
  })

  it('falls back to visibility polling on SSE error and closes on terminal response', async () => {
    const onMessage = vi.fn()
    const onTerminal = vi.fn()
    api.get
      .mockResolvedValueOnce({ id: 88, status: 'RUNNING', summary: '轮询中' })
      .mockResolvedValueOnce({ id: 88, status: 'FAILED', summary: '失败' })

    const scope = effectScope()
    const stream = scope.run(() => useExecutionStream({ fallbackIntervalMs: 500 }))
    stream.subscribe(88, { onMessage, onTerminal })

    instances[0].onerror()
    expect(instances[0].closed).toBe(true)
    expect(stream.mode.value).toBe('polling')

    await Promise.resolve()
    await Promise.resolve()
    expect(api.get).toHaveBeenCalledWith('/executions/runs/88', expect.objectContaining({ signal: expect.any(Object) }))
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ status: 'RUNNING' }), 88)

    await vi.advanceTimersByTimeAsync(500)
    await Promise.resolve()
    await Promise.resolve()
    expect(onTerminal).toHaveBeenCalledWith(expect.objectContaining({ status: 'FAILED' }), 88)
    expect(stream.mode.value).toBe('closed')

    scope.stop()
  })

  it('routes async onTerminal rejection into onError instead of leaking unhandled rejection', async () => {
    const boom = new Error('refresh failed')
    const onError = vi.fn()
    const onTerminal = vi.fn().mockRejectedValueOnce(boom)

    const scope = effectScope()
    const stream = scope.run(() => useExecutionStream())
    stream.subscribe(55, { onTerminal, onError })

    instances[0].onmessage({ data: JSON.stringify({ id: 55, status: 'SUCCESS' }) })
    await Promise.resolve()
    await Promise.resolve()

    expect(onError).toHaveBeenCalledWith(boom, 55)
    scope.stop()
  })
})
