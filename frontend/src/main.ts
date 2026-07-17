import { createApp } from 'vue'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'

import 'primeicons/primeicons.css'
import './style.css'
import App from './App.vue'
import { OracleTheme } from './theme'
import { initColorScheme } from './colorScheme'

initColorScheme()

createApp(App)
  .use(PrimeVue, {
    theme: { preset: OracleTheme, options: { darkModeSelector: '.oracle-dark' } },
  })
  .use(ToastService)
  .mount('#app')
