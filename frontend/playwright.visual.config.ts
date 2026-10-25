import { defineConfig, devices } from '@playwright/test'

const PORT = 5174
const BASE_URL = `http://127.0.0.1:${PORT}`

// Baselines are only valid in the Playwright container (see CLAUDE.md), so the
// name carries no platform suffix: one image, one set of baselines.
export default defineConfig({
  testDir: './e2e/visual',
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}{ext}',
  retries: 0,
  fullyParallel: true,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    colorScheme: 'light',
    timezoneId: 'UTC',
    locale: 'en-US',
  },
  expect: { toHaveScreenshot: { caret: 'hide', animations: 'disabled' } },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } }],
  webServer: {
    command: `./node_modules/.bin/vite --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: false,
  },
})
