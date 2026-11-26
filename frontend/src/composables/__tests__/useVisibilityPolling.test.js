import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVisibilityPolling } from '../useVisibilityPolling'

function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state
  })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('useVisibilityPolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setVisibility('visible')
  })

  afterEach(() => {
    setVisibility('visible')
    vi.useRealTimers()
  })

  it('chains timeouts after async work settles without overlapping ticks', async () => {
    const resolvers = []
    const task = vi.fn(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve)
        })
    )

    const scope = effectScope()
    const poller = scope.run(() => useVisibilityPolling(task, { intervalMs: 1000 }))
    poller.start({ immediate: true })

    expect(task).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    // Still waiting for first async call -> zero overlapping calls
    expect(task).toHaveBeenCalledTimes(1)

    resolvers.shift()()
    await Promise.resolve()
    await Promise.resolve()

    await vi.advanceTimersByTimeAsync(999)
    expect(task).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(task).toHaveBeenCalledTimes(2)

    scope.stop()
  })

  it('defers execution when initially hidden and triggers catch-up on visible', async () => {
    setVisibility('hidden')
    const task = vi.fn().mockResolvedValue(undefined)

    const scope = effectScope()
    const poller = scope.run(() => useVisibilityPolling(task, { intervalMs: 500 }))
    poller.start({ immediate: true })

    expect(poller.isPaused.value).toBe(true)
    await vi.advanceTimersByTimeAsync(3000)
    expect(task).not.toHaveBeenCalled()

    setVisibility('visible')
    await Promise.resolve()
    expect(poller.isPaused.value).toBe(false)
    expect(task).toHaveBeenCalledTimes(1)

    setVisibility('hidden')
    expect(poller.isPaused.value).toBe(true)
    await vi.advanceTimersByTimeAsync(2000)
    expect(task).toHaveBeenCalledTimes(1)

    setVisibility('visible')
    await Promise.resolve()
    expect(task).toHaveBeenCalledTimes(2)

    scope.stop()
  })

  it('aborts in-flight request when stopped and cleans up on scope dispose', async () => {
    let capturedSignal = null
    const task = vi.fn(
      ({ signal }) =>
        new Promise((_resolve, reject) => {
          capturedSignal = signal
          signal.addEventListener('abort', () => {
            const err = new Error('aborted')
            err.name = 'AbortError'
            reject(err)
          })
        })
    )
    const onError = vi.fn()

    const scope = effectScope()
    const poller = scope.run(() => useVisibilityPolling(task, { intervalMs: 500, onError }))
    poller.start({ immediate: true })

    expect(capturedSignal.aborted).toBe(false)
    scope.stop()
    await Promise.resolve()

    expect(capturedSignal.aborted).toBe(true)
    expect(poller.isRunning.value).toBe(false)
    expect(onError).not.toHaveBeenCalled()
  })

  it('preserves active inFlightPromise when an earlier aborted tick settles after refresh()', async () => {
    const deferred = []
    const task = vi.fn(
      ({ signal }) =>
        new Promise((resolve, reject) => {
          signal.addEventListener('abort', () => {
            const err = new Error('aborted')
            err.name = 'AbortError'
            reject(err)
          })
          deferred.push(resolve)
        })
    )

    const scope = effectScope()
    const poller = scope.run(() => useVisibilityPolling(task, { intervalMs: 500 }))
    poller.start({ immediate: true })
    expect(task).toHaveBeenCalledTimes(1)

    // refresh() aborts tick 1 and immediately starts tick 2
    poller.refresh()
    expect(task).toHaveBeenCalledTimes(2)

    // Let tick 1's rejection settle, then toggle visibility -> tick 2 is still in flight so tick 3 must NOT start
    await Promise.resolve()
    await Promise.resolve()
    setVisibility('hidden')
    setVisibility('visible')
    expect(task).toHaveBeenCalledTimes(2)

    deferred[1]()
    await Promise.resolve()
    scope.stop()
  })
})
