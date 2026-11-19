const STORAGE_KEY = 'tp_active_project_id'

export function getSavedProjectId(projects = []) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return undefined
    const num = Number(raw)
    if (!Number.isFinite(num) || num <= 0) return undefined
    if (Array.isArray(projects) && projects.length > 0) {
      return projects.some((p) => Number(p.id) === num) ? num : undefined
    }
    return num
  } catch {
    return undefined
  }
}

export function saveActiveProjectId(projectId) {
  try {
    if (projectId === undefined || projectId === null || projectId === '') {
      localStorage.removeItem(STORAGE_KEY)
    } else {
      localStorage.setItem(STORAGE_KEY, String(projectId))
    }
  } catch {
    // ignore storage errors
  }
}
