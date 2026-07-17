import { createApp } from 'vue'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'

import 'primeicons/primeicons.css'
import './style.css'
import App from './App.vue'
import { OracleTheme } from './theme'

// The redesign is dark-only (no light variant), so the selector is applied
// once, permanently, rather than toggled with a system preference.
document.documentElement.classList.add('oracle-dark')

createApp(App)
  .use(PrimeVue, {
    theme: { preset: OracleTheme, options: { darkModeSelector: '.oracle-dark' } },
  })
  .use(ToastService)
  .mount('#app')
