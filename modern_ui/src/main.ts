import { createApp } from 'vue'
import App from './App.vue'
import './palette.css'
import './style.css'

try {
  let failed = false
  const app = createApp(App)
  app.config.errorHandler = (error, _instance, info) => {
    failed = true
    const detail = `${info}: ${error instanceof Error ? error.message : String(error)}`
    window.__kohyaStartup?.report('page_error', detail)
    window.__kohyaStartup?.fail(detail)
  }
  app.mount('#app')
  if (!failed) window.__kohyaStartup?.mounted()
} catch (error) {
  window.__kohyaStartup?.fail(error instanceof Error ? error.message : String(error))
}
