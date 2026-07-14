import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const BASE_URL = 'http://127.0.0.1:5173'

const E2E_DATA_DIR = fileURLToPath(new URL('./e2e/.data', import.meta.url))

export default defineConfig({
  testDir: './e2e',
  retries: 0,
  use: { baseURL: BASE_URL, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `rm -rf ${E2E_DATA_DIR} && uv run --directory ../backend oracle-server`,
      url: 'http://127.0.0.1:8000/health',
      env: {
        ORACLE_DB_PATH: `${E2E_DATA_DIR}/oracle.db`,
        ORACLE_UPLOADS_DIR: `${E2E_DATA_DIR}/uploads`,
      },
      reuseExistingServer: false,
      stdout: 'pipe',
    },
    {
      command: 'pnpm dev',
      url: BASE_URL,
      reuseExistingServer: !process.env.CI,
    },
  ],
})
