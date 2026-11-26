import { onScopeDispose, readonly, ref } from 'vue'
import { api, isAbortError } from '@/lib/api'
import { useVisibilityPolling } from '@/composables/useVisibilityPolling'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const TERMINAL_STATUSES = new Set(['SUCCESS', 'FAILED', 'ERROR', 'TIMEOUT', 'CANCELLED'])

export function isTerminalExecutionStatus(status) {
  return TERMINAL_STATUSES.has(String(status || '').toUpperCase())
}

export function useExecutionStream(defaultOptions = {}) {
  const activeRunId = ref(null)
  const mode = ref('idle') // 'idle' | 'connecting' | 'sse' | 'polling' | 'closed'

  let eventSource = null
  let currentCallbacks = {}
  let currentRunId = null
  let sessionEpoch = 0

  const fallbackPoller = useVisibilityPolling(
    async ({ signal }) => {
      const targetRunId = currentRunId
      const epoch = sessionEpoch
      if (!targetRunId) return
      try {
        const fetchFn =
          currentCallbacks.fetchStatus ||
          defaultOptions.fetchStatus ||
          ((id, reqOpts) => api.get(`/executions/runs/${id}`, reqOpts))
        const payload = await fetchFn(targetRunId, { signal })
        if (epoch !== sessionEpoch || currentRunId !== targetRunId || !payload) return
        currentCallbacks.onMessage?.(payload, targetRunId)
        if (isTerminalExecutionStatus(payload.status)) {
          const onTerminal = currentCallbacks.onTerminal
          const onError = currentCallbacks.onError
          stop()
          mode.value = 'closed'
          Promise.resolve(onTerminal?.(payload, targetRunId)).catch((err) => {
            onError?.(err, targetRunId)
          })
        }
      } catch (error) {
        if (!isAbortError(error) && epoch === sessionEpoch) {
          currentCallbacks.onError?.(error, targetRunId)
        }
      }
    },
    {
      intervalMs: defaultOptions.fallbackIntervalMs ?? 2500
    }
  )

  function closeEventSource() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  function stop() {
    sessionEpoch += 1
    currentRunId = null
    activeRunId.value = null
    closeEventSource()
    fallbackPoller.stop()
    if (mode.value !== 'closed') {
      mode.value = 'idle'
    }
  }

  function startFallbackPolling(runId, epoch) {
    if (epoch !== sessionEpoch || currentRunId !== runId) return
    closeEventSource()
    mode.value = 'polling'
    fallbackPoller.start({ immediate: true })
  }

  function subscribe(runId, callbacks = {}) {
    stop()
    if (!runId) return

    sessionEpoch += 1
    const epoch = sessionEpoch
    currentRunId = runId
    activeRunId.value = runId
    currentCallbacks = callbacks
    mode.value = 'connecting'

    if (typeof EventSource === 'undefined') {
      startFallbackPolling(runId, epoch)
      return
    }

    const url = `${API_BASE_URL}/v1/executions/runs/${encodeURIComponent(runId)}/stream`
    const es = new EventSource(url, { withCredentials: true })
    eventSource = es

    es.onopen = () => {
      if (epoch !== sessionEpoch || eventSource !== es) return
      mode.value = 'sse'
    }

    es.onmessage = (event) => {
      if (epoch !== sessionEpoch || eventSource !== es) return
      try {
        const payload = JSON.parse(event.data)
        mode.value = 'sse'
        currentCallbacks.onMessage?.(payload, runId)
        if (isTerminalExecutionStatus(payload?.status)) {
          const onTerminal = currentCallbacks.onTerminal
          const onError = currentCallbacks.onError
          stop()
          mode.value = 'closed'
          Promise.resolve(onTerminal?.(payload, runId)).catch((err) => {
            onError?.(err, runId)
          })
        }
      } catch (error) {
        currentCallbacks.onError?.(error, runId)
      }
    }

    es.onerror = () => {
      if (epoch !== sessionEpoch || eventSource !== es) return
      startFallbackPolling(runId, epoch)
    }
  }

  onScopeDispose(() => {
    stop()
  })

  return {
    activeRunId: readonly(activeRunId),
    mode: readonly(mode),
    subscribe,
    stop
  }
}
