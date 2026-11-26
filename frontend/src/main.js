import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/global.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const RECENT_CLIENT_ERRORS = new Map()

function reportClientError({ source, message, stack, component }) {
  try {
    if (!message || String(message).trim() === '') return
    const msg = String(message).slice(0, 1500)
    const key = `${source}:${msg}`
    const now = Date.now()
    const prev = RECENT_CLIENT_ERRORS.get(key) || 0
    if (now - prev < 5000) return
    if (RECENT_CLIENT_ERRORS.size > 100) {
      RECENT_CLIENT_ERRORS.clear()
    }
    RECENT_CLIENT_ERRORS.set(key, now)

    const payload = JSON.stringify({
      source,
      message: msg,
      stack: stack ? String(stack).slice(0, 6000) : null,
      component: component ? String(component).slice(0, 180) : null,
      route: typeof window !== 'undefined' ? window.location.pathname : null
    })
    fetch(`${API_BASE_URL}/v1/system/client-errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true
    }).catch(() => {})
  } catch {
    // never cascade runtime error reporting
  }
}

const app = createApp(App)

app.config.errorHandler = (err, instance, info) => {
  console.error(err)
  if (err?.name === 'AbortError') return
  const componentName = instance?.$options?.name || instance?.$options?.__name || info || 'unknown'
  reportClientError({
    source: 'vue',
    message: err?.message || String(err),
    stack: err?.stack || null,
    component: componentName
  })
}

if (typeof window !== 'undefined') {
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event?.reason
    if (reason?.name === 'AbortError') return
    reportClientError({
      source: 'promise',
      message: reason?.message || String(reason || 'Unhandled promise rejection'),
      stack: reason?.stack || null
    })
  })
}

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)

app.mount('#app')
