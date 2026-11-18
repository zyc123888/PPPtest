import { readonly, ref } from 'vue'

export function useSubmitGuard() {
  const pending = ref(false)

  const run = async (action) => {
    if (pending.value) return { skipped: true }
    pending.value = true
    try {
      return await action()
    } finally {
      pending.value = false
    }
  }

  return { pending: readonly(pending), run }
}
