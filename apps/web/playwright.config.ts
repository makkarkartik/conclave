import { defineConfig } from '@playwright/test'

/**
 * E2E suite. Prerequisite: the dev Postgres must be up (docker compose up -d db).
 * Playwright starts both servers itself:
 *  - API on :8000 with the deterministic fake LLM provider enabled
 *  - Vite dev server on :5173 (proxies /api to :8000)
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    // localhost, not 127.0.0.1: vite binds the hostname, which resolves to ::1 here
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'python -m conclave.serve --port 8000',
      cwd: '../api',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        CONCLAVE_ENABLE_FAKE_PROVIDER: '1',
        CONCLAVE_FAKE_TURN_DELAY: '0.7',
      },
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
