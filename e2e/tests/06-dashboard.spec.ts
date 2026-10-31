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

/** Browser-level coverage for the current React admin dashboard. */
test.describe('Admin dashboard (real browser, real admin API)', () => {
  let errors: string[]

  test.beforeAll(async () => {
    const api = await createClient()
    try {
      const user = await createUser(api)
      const captureId = newCaptureId()
      await scriptTranscript(api, captureId, 'Dashboard seed: Echo depends on FastAPI.')
      const up = await uploadCapture(api, user, captureId)
      expect(up.res.status()).toBe(202)
      await expect.poll(async () => (await waitTerminal(api, user, captureId)).status).toBe('ready')
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
    await page.getByLabel('Admin token').fill(ADMIN_TOKEN)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  }

  test('without a token stays on the admin sign-in screen', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Knowledge operations, clearly.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeDisabled()
  })

  test('valid token loads live overview and preserves intentional TODO entries', async ({ page }) => {
    await login(page)
    await expect(page.getByText('Connected')).toBeVisible()
    await expect(page.getByRole('button', { name: /System Operations/ })).toBeDisabled()
    await expect(page.getByRole('button', { name: /Monitoring/ })).toBeDisabled()
    await expect(page.getByText('Capture processing')).toBeVisible()
  })

  test('captures list and detail use the current admin API', async ({ page }) => {
    await login(page)
    await page.getByRole('button', { name: 'Captures' }).click()
    await expect(page.getByPlaceholder('Search capture ID or owner')).toBeVisible()
    await expect(page.getByRole('button', { name: /…/ }).first()).toBeVisible({ timeout: 15_000 })
    await page.getByRole('button', { name: /…/ }).first().click()
    await expect(page.getByText('CAPTURE DETAIL')).toBeVisible()
    await expect(page.getByText('Extracted entities')).toBeVisible()
  })

  test('knowledge graph navigation exposes read-only entity and relationship views', async ({ page }) => {
    await login(page)
    await page.getByRole('button', { name: 'Knowledge Graph' }).click()
    await expect(page.getByRole('button', { name: 'Entities' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Relationships' })).toBeVisible()
    await page.getByRole('button', { name: 'Relationships' }).click()
    await expect(page.getByPlaceholder('Search relationships')).toBeVisible()
  })

  test.afterEach(async ({}, testInfo) => {
    if (testInfo.status !== 'passed' && errors.length > 0) {
      console.error(`[${testInfo.title}] browser errors:`, errors)
      expect(errors, JSON.stringify(errors)).toHaveLength(0)
    }
  })
})
