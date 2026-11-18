export function buildCaseBatchPatch(form = {}) {
  const patch = {}
  if (form.folder_mode === 'clear') patch.folder_path = null
  if (form.folder_mode === 'set' && String(form.folder_path || '').trim()) {
    patch.folder_path = String(form.folder_path).trim()
  }
  if (form.priority_mode === 'set' && form.priority) patch.priority = form.priority
  if (form.status_mode === 'set' && form.status) patch.status = form.status
  if (form.tags_mode === 'clear') patch.tags_json = null
  if (form.tags_mode === 'set') patch.tags_json = [...(form.tags_json || [])]
  return patch
}
