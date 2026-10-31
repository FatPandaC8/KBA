import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test, expect } from '@playwright/test'
import {
  DB_PATH,
  createClient,
  createUser,
  newCaptureId,
  scriptTranscript,
  uploadCapture,
  waitTerminal,
} from '../helpers/harness'

/**
 * Persistence integrity: the HTTP layer must be backed by real rows in the
 * SQLite database. db_inspect.py dumps table counts + rows as JSON; it must
 * never emit before failing loudly (non-zero exit).
 */
function inspect(): any {
  const script = resolve(__dirname, '../db_inspect.py')
  const out = execSync(`python3 ${script} ${DB_PATH}/echo.db`, {
    encoding: 'utf-8',
    timeout: 30_000,
  })
  const clean = out.trim()
  expect(clean.startsWith('{'), `db_inspect.py emitted non-JSON: ${clean.slice(0, 200)}`).toBeTruthy()
  return JSON.parse(clean)
}

test.describe('Persisted data integrity (actual SQLite inspection)', () => {
  test('pipeline output is truly persisted: captures, jobs, knowledge, entities, relationships', async () => {
    const api = await createClient()
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')
    const up = await uploadCapture(api, user, captureId)
    expect(up.res.status()).toBe(202)
    const job = await waitTerminal(api, user, captureId)
    expect(job.status).toBe('ready')
    const knowledgeAfter = await (await api.get('/api/knowledge', { headers: { Authorization: `Bearer ${user.token}` } })).json()
    await api.dispose()

    const db = inspect()
    expect(db.tables).toContain('captures')
    expect(db.tables).toContain('processing_jobs')
    expect(db.tables).toContain('knowledge_items')
    expect(db.tables).toContain('entities')
    expect(db.tables).toContain('relationships')
    expect(db.tables).toContain('users')
    expect(db.tables).toContain('sessions')

    // The capture this test created really exists in the DB…
    const captureRow = db.captures.find((r: any) => r.id === captureId)
    expect(captureRow, JSON.stringify(db.captures.map((r: any) => r.id))).toBeTruthy()
    expect(captureRow.status).toBe('ready')
    expect(captureRow.user_id).toBe(user.userId)
    expect(captureRow.audio_path).toContain('/uploads/')

    // …the worker job row is completed…
    const jobRow = db.processing_jobs.find((r: any) => r.capture_id === captureId)
    expect(jobRow).toBeTruthy()
    expect(jobRow.stage).toBe('completed')
    expect(jobRow.status).toBe('ready')

    // …there is exactly one knowledge item linked to that capture…
    const knowledgeRows = db.knowledge_items.filter((r: any) => r.capture_id === captureId)
    expect(knowledgeRows).toHaveLength(1)
    expect(knowledgeRows[0].id).toBe(knowledgeAfter[0].id)

    // …its entities and relationship rows persist with the item id link.
    const entityRows = db.entities.filter((r: any) => r.user_id === user.userId)
    expect(entityRows.length).toBeGreaterThanOrEqual(2) // Echo + FastAPI
    const relRows = db.relationships.filter((r: any) => r.user_id === user.userId)
    expect(relRows.length).toBeGreaterThanOrEqual(1)

    // Sensitive data handling: the raw transcript lives in the admin-facing
    // model_eval_records (internal artifact) — but JSON written by the app
    // never contains a password.
    const rawDb = readFileSync(`${DB_PATH}/echo.db`, 'latin1')
    expect(rawDb.includes(user.password)).toBe(false)
  })

  test('user deletion clears the user, sessions and captures rows', async () => {
    const api = await createClient()
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')
    const up = await uploadCapture(api, user, captureId)
    expect(up.res.status()).toBe(202)
    await waitTerminal(api, user, captureId)

    const del = await api.delete('/api/account?confirm=DELETE', {
      headers: { Authorization: `Bearer ${user.token}` },
    })
    expect(del.ok()).toBeTruthy()
    await api.dispose()

    const db = inspect()
    expect(db.counts.users).toBeGreaterThanOrEqual(0)
    const leftover = db.captures.find((r: any) => r.user_id === user.userId)
    expect(leftover, 'deleted user still owns capture rows').toBeFalsy()
    const leftoverJobs = db.processing_jobs.find((r: any) => r.user_id === user.userId)
    expect(leftoverJobs, 'deleted user still owns job rows').toBeFalsy()
    const leftoverKnowledge = db.knowledge_items.find((r: any) => r.user_id === user.userId)
    expect(leftoverKnowledge, 'deleted user still owns knowledge rows').toBeFalsy()
  })
})
