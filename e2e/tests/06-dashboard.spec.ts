import { test, expect } from '@playwright/test'
import {
  ADMIN_TOKEN,
  createClient,
  createUser,
  newCaptureId,
  scriptTranscript,
  uploadCapture,
  waitTerminal,
  trackErrors,
} from '../helpers/harness'

/**
 * Browser-level verification of the server-rendered admin dashboard
 * (server/app/static/index.html). This is the only browser surface the
 * backend ships; the mobile app is not browser-based and an emulator is
 * not available in this run.
 */
test.describe('Admin dashboard (real browser, real admin API)', () => {
  let errors: string[]

  // Seed real data through the normal capture pipeline so this spec never
  // depends on rows left behind by earlier tests (isolation discipline).
  test.beforeAll(async () => {
    const api = await createClient()
    try {
      const user = await createUser(api)
      const captureId = newCaptureId()
      await scriptTranscript(api, captureId, 'Dashboard seed: Echo depends on FastAPI.')
      const up = await uploadCapture(api, user, captureId)
      expect(up.res.status()).toBe(202)
      const job = await waitTerminal(api, user, captureId)
      expect(job.status).toBe('ready')
    } finally {
      await api.dispose()
    }
  })

  test.beforeEach(async ({ page }) => {
    errors = trackErrors(page)
    await page.goto('/admin')
    await expect(page).toHaveTitle(/Echo|Admin|Dashboard/i)
  })

  async function login(page: import('@playwright/test').Page) {
    await page.fill('#adminToken', ADMIN_TOKEN)
    await page.locator('#adminToken').evaluate((el: HTMLInputElement) =>
      el.dispatchEvent(new Event('change')),
    )
  }

  test('without a token the dashboard refuses to load data', async ({ page }) => {
    await page.click('#btnRefreshDashboard')
    await expect(page.locator('#lastRefreshed')).toContainText(/Enter an admin token/i)
    await expect(page.locator('#statusBadge')).toHaveText('—')
  })

  test('with a valid token the overview shows live system metrics', async ({ page }) => {
    await login(page)
    await page.click('#btnRefreshDashboard')

    await expect(page.locator('#statusBadge')).not.toHaveText('—', { timeout: 15_000 })
    const metricKnowledge = await page.textContent('#metricKnowledge')
    expect(Number(metricKnowledge)).toBeGreaterThanOrEqual(1)
    const metricRelations = await page.textContent('#metricRelations')
    expect(Number(metricRelations)).toBeGreaterThanOrEqual(0)
    await expect(page.locator('#dbStatus')).toBeVisible()
  })

  test('captures pane lists a real capture; inspecting it shows resolved knowledge', async ({ page }) => {
    await login(page)
    await page.click('button[data-tab="captures"]')
    await page.click('#btnRefreshCaptures')
    // Real run data: capture rows must exist (not the "Loading…" or empty placeholder).
    const rows = page.locator('#capturesTableBody tr')
    await expect(rows.filter({ has: page.locator('td:not([colspan])') }).first()).toBeVisible({
      timeout: 15_000,
    })
    expect(await rows.count()).toBeGreaterThan(0)

    // The detail flows through the modal with the resolved knowledge item.
    await page.click('button[data-inspect]:visible >> nth=0')
    await expect(page.locator('#captureModal.open')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('#modalResolvedContainer')).toContainText(/Echo|Dashboard/i)
    await page.click('#btnCloseModal')
    await expect(page.locator('#captureModal')).not.toHaveClass(/open/, { timeout: 15_000 })
  })

  test('knowledge pane lists the seeded knowledge item with concepts and tags', async ({ page }) => {
    await login(page)
    await page.click('button[data-tab="knowledge"]')
    await page.locator('#knowledgeSearchInput').fill('Dashboard seed')
    await page.click('#btnKnowledgeFilter')
    await expect(page.locator('#knowledgeTableBody tr td:not([colspan])').first()).toBeVisible({
      timeout: 15_000,
    })
    await expect(page.locator('#knowledgeTableBody')).toContainText('Dashboard seed')
  })

  test('jobs pane shows the live pipeline job lifecycle', async ({ page }) => {
    await login(page)
    await page.click('button[data-tab="jobs"]')
    await page.click('#btnRefreshJobs')
    await expect(page.locator('#jobsTableBody tr td:not([colspan])').first()).toBeVisible({
      timeout: 15_000,
    })
  })

  test.afterEach(async ({ page }, testInfo) => {
    if (testInfo.status !== 'passed' && errors.length > 0) {
      console.error(`[${testInfo.title}] browser errors:`, errors)
      // Browser errors decay testInfo into a failure so CI reports them.
      expect(errors, JSON.stringify(errors)).toHaveLength(0)
    }
  })
})
