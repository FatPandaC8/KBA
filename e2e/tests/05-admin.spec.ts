import { test, expect } from '@playwright/test'
import {
  adminHeaders,
  createClient,
  createUser,
  newCaptureId,
  scriptTranscript,
  uploadCapture,
  waitTerminal,
} from '../helpers/harness'

test.describe('Admin API: status, jobs, captures, audit (token-gated)', () => {
  let api: Awaited<ReturnType<typeof createClient>>
  let user: { email: string; password: string; token: string; userId: string }
  let captureId: string

  test.beforeAll(async () => {
    api = await createClient()
    user = await createUser(api)
    captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI. Alice runs the Echo project.')
    const up = await uploadCapture(api, user, captureId)
    expect(up.res.status()).toBe(202)
    const job = await waitTerminal(api, user, captureId)
    expect(job.status).toBe('ready')
  })
  test.afterAll(async () => {
    await api.dispose()
  })

  test('admin endpoints fail closed without the admin token', async () => {
    expect((await api.get('/api/admin/status')).status()).toBe(401)
    expect((await api.get('/api/admin/status', { headers: { Authorization: 'Bearer wrong-token' } })).status()).toBe(401)
    // A normal user's session token is NOT an admin token (U4-boundary).
    const userRes = await api.get('/api/admin/status', { headers: { Authorization: `Bearer ${user.token}` } })
    expect(userRes.status()).toBe(401)
  })

  test('status reports service health and counts', async () => {
    const res = await api.get('/api/admin/status', { headers: adminHeaders() })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.status).toBeTruthy()
    expect(body.service).toBeTruthy()
    expect(body.knowledge_count).toBeGreaterThan(0)
    expect(body.relationship_count).toBeGreaterThan(0)
    expect(typeof body.audio_storage_bytes).toBe('number')
  })

  test('recent jobs and capture details include the transcript (admin-only access)', async () => {
    const jobs = await api.get('/api/admin/jobs', { headers: adminHeaders() })
    expect(jobs.ok()).toBeTruthy()
    const jobList = await jobs.json()
    expect(jobList.some((j: any) => j.capture_id === captureId)).toBe(true)

    const captures = await api.get('/api/admin/captures', { headers: adminHeaders() })
    expect(captures.ok()).toBeTruthy()
    const captureList = await captures.json()
    const mine = captureList.find((c: any) => c.capture_id === captureId)
    expect(mine).toBeTruthy()
    expect(mine.has_audio).toBe(true)

    // Transcript is visible ONLY through admin detail (audit-backed access).
    const detail = await api.get(`/api/admin/captures/${captureId}`, { headers: adminHeaders() })
    expect(detail.ok()).toBeTruthy()
    const d = await detail.json()
    expect(d.original_transcript.toLowerCase()).toContain('echo depends on fastapi')

    // The same transcript is NOT visible to the owning user (D5/C3).
    const userView = await api.get(`/api/recordings/${captureId}/status`, {
      headers: { Authorization: `Bearer ${user.token}` },
    })
    const text = JSON.stringify(await userView.json()).toLowerCase()
    expect(text.includes('echo depends on fastapi')).toBe(false)
  })

  test('admin knowledge delete endpoint removes data and audits the action', async () => {
    // Create a capture specifically for deletion.
    const victimCapture = newCaptureId()
    await scriptTranscript(api, victimCapture, 'Echo depends on Postgres for storage.')
    await uploadCapture(api, user, victimCapture)
    await waitTerminal(api, user, victimCapture)

    const adminKnowledge = await api.get('/api/admin/knowledge', { headers: adminHeaders() })
    expect(adminKnowledge.ok()).toBeTruthy()
    const rows = await adminKnowledge.json()
    const victim = rows.find((k: any) => k.capture_id === victimCapture)
    expect(victim).toBeTruthy()

    const del = await api.delete(`/api/admin/knowledge/${victim.id}`, { headers: adminHeaders() })
    expect(del.status()).toBe(200)

    // The user no longer sees that knowledge item…
    const userKnowledge = await api.get('/api/knowledge', {
      headers: { Authorization: `Bearer ${user.token}` },
    })
    const remaining = (await userKnowledge.json()).filter((k: any) => k.capture_id === victimCapture)
    expect(remaining).toHaveLength(0)

    // …and the action landed in the admin audit log (U4).
    const audit = await api.get('/api/admin/audit-log', { headers: adminHeaders() })
    expect(audit.ok()).toBeTruthy()
    const auditBody = await audit.json()
    const actions = auditBody.rows.map((r: any) => r.action)
    expect(actions).toContain('knowledge.delete')
    const deleteRow = auditBody.rows.find((r: any) => r.action === 'knowledge.delete')
    expect(deleteRow.actor).toBe('admin')
    expect(typeof deleteRow.detail === 'string' || deleteRow.detail === '').toBe(true)
  })

  test('config endpoints reflect safe defaults; no API key material is returned', async () => {
    const config = await api.get('/api/admin/config', { headers: adminHeaders() })
    expect(config.ok()).toBeTruthy()
    const cfg = await config.json()
    expect(cfg.environment).toBeTruthy()
    expect(cfg.max_voice_seconds).toBeGreaterThan(0)
    const text = await config.text()
    expect(/\b(sk|gsk_)[A-Za-z0-9]{10,}/.test(text), 'secret-shaped token in config response').toBe(false)

    const ai = await api.get('/api/admin/ai-config', { headers: adminHeaders() })
    expect(ai.ok()).toBeTruthy()
    const aiBody = await ai.json()
    expect(['rule_based', 'groq', 'fake']).toContain(aiBody.provider)

    // Invalid provider switch is rejected and audited as rejected.
    const bad = await api.put('/api/admin/ai-config', {
      headers: adminHeaders(),
      data: { provider: 'definitely-not-a-provider', model: '' },
    })
    expect(bad.status()).toBe(400)

    const audit = await (await api.get('/api/admin/audit-log', { headers: adminHeaders() })).json()
    const rejected = audit.rows.find((r: any) => r.action === 'ai_config.update' && r.outcome === 'rejected')
    expect(rejected).toBeTruthy()
  })

  test('embeddings backfill endpoint returns a real summary', async () => {
    const res = await api.post('/api/admin/embeddings/backfill', { headers: adminHeaders() })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.total_items).toBeGreaterThan(0)
    expect(typeof body.newly_indexed).toBe('number')
    expect(typeof body.failed).toBe('number')
  })

  test('worker can be operated through admin retry for a failed job', async () => {
    const failCapture = newCaptureId()
    // Intentionally leave no STT script: harness transcriber raises a typed error.
    const up = await uploadCapture(api, user, failCapture)
    expect(up.res.status()).toBe(202)
    const failed = await waitTerminal(api, user, failCapture)
    expect(failed.status).toBe('failed')

    const jobs = await (await api.get('/api/admin/jobs', { headers: adminHeaders() })).json()
    const job = jobs.find((j: any) => j.capture_id === failCapture)
    expect(job).toBeTruthy()

    const retry = await api.post(`/api/admin/jobs/${failCapture}/retry`, { headers: adminHeaders() })
    expect([200, 409]).toContain(retry.status())
  })
})
