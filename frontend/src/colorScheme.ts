import { ref } from 'vue'

type ColorScheme = 'light' | 'dark'

const STORAGE_KEY = 'oracle-color-scheme'

function systemPreference(): ColorScheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function storedPreference(): ColorScheme | null {
  const stored = localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : null
}

export const colorScheme = ref<ColorScheme>(systemPreference())

function apply(scheme: ColorScheme) {
  colorScheme.value = scheme
  document.documentElement.classList.toggle('oracle-dark', scheme === 'dark')
}

export function initColorScheme() {
  apply(storedPreference() ?? systemPreference())

  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
    if (storedPreference()) return
    apply(event.matches ? 'dark' : 'light')
  })
}

export function toggleColorScheme() {
  const next: ColorScheme = colorScheme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem(STORAGE_KEY, next)
  apply(next)
}
