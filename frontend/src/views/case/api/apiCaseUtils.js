export function formatDebugBody(body) {
  if (body === null || body === undefined) return ''
  if (typeof body === 'string') return body
  try {
    return JSON.stringify(body, null, 2)
  } catch {
    return String(body)
  }
}

export function parseQueryParamsFromPath(path) {
  const raw = String(path || '')
  const idx = raw.indexOf('?')
  if (idx === -1) return []
  const queryPart = raw.slice(idx + 1)
  if (!queryPart) return []
  return queryPart
    .split('&')
    .filter(Boolean)
    .map((pair) => {
      const [key, ...rest] = pair.split('=')
      return {
        enabled: true,
        key: decodeURIComponent(key || ''),
        value: decodeURIComponent(rest.join('=') || '')
      }
    })
}
