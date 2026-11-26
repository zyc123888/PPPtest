import { onScopeDispose, readonly, ref, unref } from 'vue'
import { isAbortError } from '@/lib/api'

function isDocumentHidden() {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden'
}

export function useVisibilityPolling(fn, options = {}) {
  const isRunning = ref(false)
  const isPaused = ref(false)

  let timerId = null
  let activeController = null
  let inFlightPromise = null
  let generation = 0
  let listenerAttached = false
  let needsCatchUp = false

  function getIntervalMs() {
    const raw = Number(unref(options.intervalMs ?? 3000))
    return Number.isFinite(raw) && raw >= 50 ? raw : 3000
  }

  function clearTimer() {
    if (timerId !== null) {
      clearTimeout(timerId)
      timerId = null
    }
  }

  function abortActiveRequest() {
    if (activeController) {
      activeController.abort()
      activeController = null
    }
  }

  function scheduleNext(runGen) {
    clearTimer()
    if (!isRunning.value || runGen !== generation || isDocumentHidden()) {
      return
    }
    timerId = setTimeout(() => {
      timerId = null
      executeTick(runGen)
    }, getIntervalMs())
  }

  async function executeTick(runGen) {
    if (!isRunning.value || runGen !== generation) return
    if (isDocumentHidden()) {
      isPaused.value = true
      needsCatchUp = true
      clearTimer()
      return
    }
    if (inFlightPromise) {
      return inFlightPromise
    }

    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    activeController = controller
    const signal = controller ? controller.signal : undefined

    const runPromise = (async () => {
      try {
        await fn({ signal })
      } catch (error) {
        if (!isAbortError(error) && typeof options.onError === 'function') {
          options.onError(error)
        }
      } finally {
        if (activeController === controller) {
          activeController = null
        }
        if (inFlightPromise === runPromise) {
          inFlightPromise = null
        }
        if (isRunning.value && runGen === generation) {
          if (isDocumentHidden()) {
            isPaused.value = true
            needsCatchUp = true
          } else {
            isPaused.value = false
            scheduleNext(runGen)
          }
        }
      }
    })()

    inFlightPromise = runPromise
    return runPromise
  }

  function handleVisibilityChange() {
    if (!isRunning.value) return
    if (isDocumentHidden()) {
      isPaused.value = true
      needsCatchUp = true
      clearTimer()
      return
    }
    isPaused.value = false
    if (needsCatchUp || timerId === null) {
      needsCatchUp = false
      executeTick(generation)
    }
  }

  function attachVisibilityListener() {
    if (listenerAttached || typeof document === 'undefined') return
    document.addEventListener('visibilitychange', handleVisibilityChange)
    listenerAttached = true
  }

  function detachVisibilityListener() {
    if (!listenerAttached || typeof document === 'undefined') return
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    listenerAttached = false
  }

  function start(startOptions = {}) {
    const immediate = startOptions.immediate ?? options.immediate ?? false
    if (isRunning.value) return
    generation += 1
    const runGen = generation
    isRunning.value = true
    attachVisibilityListener()

    if (isDocumentHidden()) {
      isPaused.value = true
      needsCatchUp = true
      return
    }

    isPaused.value = false
    needsCatchUp = false
    if (immediate) {
      executeTick(runGen)
    } else {
      scheduleNext(runGen)
    }
  }

  function stop() {
    generation += 1
    isRunning.value = false
    isPaused.value = false
    needsCatchUp = false
    clearTimer()
    abortActiveRequest()
    inFlightPromise = null
    detachVisibilityListener()
  }

  function refresh() {
    if (!isRunning.value) {
      start({ immediate: true })
      return
    }
    generation += 1
    const runGen = generation
    clearTimer()
    abortActiveRequest()
    inFlightPromise = null
    if (isDocumentHidden()) {
      isPaused.value = true
      needsCatchUp = true
      return
    }
    executeTick(runGen)
  }

  onScopeDispose(() => {
    stop()
  })

  return {
    isRunning: readonly(isRunning),
    isPaused: readonly(isPaused),
    start,
    stop,
    refresh
  }
}
