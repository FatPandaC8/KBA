import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.E2E_PORT || 8123)
const BASE_URL = `http://127.0.0.1:${PORT}`

// One shared backend process + SQLite DB for the whole run: user journeys are
// isolated by per-test users, and tests run serially so the single job worker
// is never contended. Tests never touch the developer DB: the launcher cleans
// and uses the path under /tmp only.
const workdir = process.env.E2E_WORKDIR || '/tmp/opencode/echo-e2e'
const e2eKey = process.env.E2E_KEY || 'e2e-harness-key'
const adminToken = process.env.E2E_ADMIN_TOKEN || 'e2e-admin-token-not-a-real-credential'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  maxFailures: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  globalTimeout: 15 * 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { outputFolder: 'artifacts/html-report', open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  outputDir: 'artifacts/test-results',
  webServer: {
    command: `python3 server_launcher.py`,
    url: `${BASE_URL}/api/health`,
    timeout: 60_000,
    reuseExistingServer: false,
    cwd: __dirname,
    env: {
      ECHO_ENV: 'test',
      ECHO_DB_PATH: `${workdir}/echo.db`,
      ECHO_UPLOAD_DIR: `${workdir}/uploads`,
      ECHO_EMAIL_OUTBOX: `${workdir}/outbox`,
      ECHO_ADMIN_TOKEN: adminToken,
      ECHO_LLM_PROVIDER: 'rule_based',
      ECHO_ALLOW_REAL_LLM: '0',
      ECHO_WORKER_ENABLED: '1',
      ECHO_JOB_POLL_SECONDS: '0.2',
      E2E_KEY: e2eKey,
      ECHO_E2E_KEY: e2eKey,
      ECHO_E2E_MODE: '1',
      ECHO_E2E_PORT: String(PORT),
    },
  },
})
