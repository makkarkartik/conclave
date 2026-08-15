import { defineConfig } from '@playwright/test'

/**
 * LIVE room drive: real provider, real models, real problem — through the actual UI.
 * Not part of the regular test suite. Run with:
 *
 *   $env:LIVE_PROVIDER="anthropic"; $env:LIVE_API_KEY="sk-..."; npm run test:live
 *
 * Env:
 *   LIVE_API_KEY   (required) BYOK provider key
 *   LIVE_PROVIDER  anthropic | openai | google   (default anthropic)
 *   LIVE_MODEL_A / LIVE_MODEL_B   per-expert model ids (defaults per provider)
 *   LIVE_TOPIC     the problem to deliberate (defaults to a real Conclave planning question)
 *
 * Prerequisite: docker compose up -d db. Leaves the room in place afterwards so you
 * can inspect the deliberation; screenshots land in test-results/live-shots/.
 */
export default defineConfig({
  testDir: './e2e-live',
  timeout: 15 * 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
    trace: 'off',
    video: 'off',
  },
  webServer: [
    {
      command: 'python -m conclave.serve --port 8000',
      cwd: '../api',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
