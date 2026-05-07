import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

export function usePermissions() {
  const authStore = useAuthStore()
  const role = computed(() => authStore.user?.role || 'viewer')
  const canAdmin = computed(() => role.value === 'admin')
  const canTest = computed(() => ['admin', 'tester'].includes(role.value))

  return {
    role,
    canAdmin,
    canTest
  }
}
