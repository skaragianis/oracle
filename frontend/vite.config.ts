/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The backend the dev proxy forwards to. This is resolved on the machine Vite
// runs on, not in the browser, so loopback is right even when the page is being
// viewed from another machine over the LAN (`pnpm dev --host`).
const BACKEND_ORIGIN = process.env.ORACLE_API_ORIGIN ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // Bind IPv4 loopback explicitly: `localhost` can resolve to IPv6 ::1, which
    // the Playwright webServer health check (127.0.0.1) then never reaches.
    host: '127.0.0.1',
    proxy: {
      // The SPA calls /api/*; the backend serves those routes at its root.
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.ts'],
  },
})
