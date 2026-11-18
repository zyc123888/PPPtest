import { describe, expect, it, vi } from 'vitest'
import { useSubmitGuard } from '../useSubmitGuard'

describe('useSubmitGuard', () => {
  it('ignores reentrant submissions while the first request is pending', async () => {
    let release
    const firstRequest = new Promise((resolve) => { release = resolve })
    const action = vi.fn(() => firstRequest)
    const guard = useSubmitGuard()

    const first = guard.run(action)
    const second = await guard.run(action)

    expect(action).toHaveBeenCalledTimes(1)
    expect(second).toEqual({ skipped: true })
    release('done')
    await expect(first).resolves.toBe('done')
    expect(guard.pending.value).toBe(false)
  })
})
