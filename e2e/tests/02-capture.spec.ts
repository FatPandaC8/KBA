import { test, expect } from '@playwright/test'
import {
  createClient,
  createUser,
  newCaptureId,
  scriptTranscript,
  scriptSttFailure,
  uploadCapture,
  waitTerminal,
  waitForJob,
} from '../helpers/harness'

test.describe('Capture pipeline: upload → STT → extraction → knowledge (real worker)', () => {
  let api: Awaited<ReturnType<typeof createClient>>

  test.beforeAll(async () => {
    api = await createClient()
  })

  test.afterAll(async () => {
    await api.dispose()
  })

  test('upload queues a job, the worker completes it, knowledge is produced', async ({ }, testInfo) => {
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'I met Alice about the Echo project. Echo depends on FastAPI.')

    const up = await uploadCapture(api, user, captureId)
    expect(up.res.status()).toBe(202)
    expect(up.body.status).toBe('queued')

    // real single-process worker picks it up; poll the actual endpoint
    const ready = await waitTerminal(api, user, captureId)
    expect(ready.status).toBe('ready')
    expect(ready.stage).toBe('completed')

    const recordings = await api.get('/api/recordings', { headers: { Authorization: `Bearer ${user.token}` } })
    expect(recordings.ok()).toBeTruthy()
    const list = await recordings.json()
    expect(list).toHaveLength(1)
    expect(list[0].capture_id).toBe(captureId)
    expect(list[0].status).toBe('ready')
    expect(list[0].knowledge_item_id).toBeTruthy()
    expect(list[0].has_audio).toBe(true)

    const knowledge = await api.get('/api/knowledge', { headers: { Authorization: `Bearer ${user.token}` } })
    const items = await knowledge.json()
    expect(items).toHaveLength(1)
    expect(items[0].title.toLowerCase()).toContain('echo')
    expect(Array.isArray(items[0].concepts)).toBe(true)
  })

  test('ready knowledge item follows the public schema (no transcript field at all)', async () => {
    const user = await createUser(api)
    const captureId = newCaptureId()
    const scriptedTranscript = 'The Echo project depends on FastAPI and Dart. Alice runs a pipeline near Berlin.'
    await scriptTranscript(api, captureId, scriptedTranscript)
    const up = await uploadCapture(api, user, captureId)
    expect(up.res.status()).toBe(202)
    await waitTerminal(api, user, captureId)

    const knowledge = await api.get('/api/knowledge', { headers: { Authorization: `Bearer ${user.token}` } })
    const items = await knowledge.json()
    expect(items).toHaveLength(1)

    const detailRaw = await (await api.get(`/api/knowledge/${items[0].id}`, { headers: { Authorization: `Bearer ${user.token}` } })).text()
    const detail = JSON.parse(detailRaw)
    // D5/C3: the *transcript artifact* must never surface through a
    // user-facing route. The public schema has no transcript key at all —
    // extracted fields (title/core_idea/details) are derived knowledge.
    expect(detail.transcript).toBeUndefined()
    expect(Object.keys(detail)).not.toContain('transcript')
    // The admin-only transcript access is exposed nowhere in user endpoints:
    // the eval/export and original_transcript fields are admin schemas.
    expect(detailRaw.includes('original_transcript')).toBe(false)
    expect(detailRaw.includes('eval_export')).toBe(false)

    // The job-status endpoint also carries no transcript material.
    const statusBody = await (await api.get(`/api/recordings/${captureId}/status`, { headers: { Authorization: `Bearer ${user.token}` } })).text()
    expect(statusBody.toLowerCase().includes('"transcript"')).toBe(false)
  })

  test('re-upload with the same idempotency key is idempotent (no duplicate)', async () => {
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')

    const first = await uploadCapture(api, user, captureId)
    expect(first.res.status()).toBe(202)
    await waitTerminal(api, user, captureId)

    const again = await uploadCapture(api, user, captureId)
    expect([200, 202]).toContain(again.res.status())

    const recordings = await (await api.get('/api/recordings', { headers: { Authorization: `Bearer ${user.token}` } })).json()
    expect(recordings).toHaveLength(1)
    const knowledge = await (await api.get('/api/knowledge', { headers: { Authorization: `Bearer ${user.token}` } })).json()
    expect(knowledge).toHaveLength(1)
  })

  test('uploaded audio is retrievable via the audio endpoint', async () => {
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')
    await uploadCapture(api, user, captureId)
    await waitTerminal(api, user, captureId)

    const audio = await api.get(`/api/recordings/${captureId}/audio`, { headers: { Authorization: `Bearer ${user.token}` } })
    expect(audio.status()).toBe(200)
    expect((await audio.body())?.length).toBeGreaterThan(0)
  })

  test('duration and content-type validation rejects bad uploads', async () => {
    const user = await createUser(api)

    // duration_ms above ECHO_MAX_VOICE_SECONDS + grace => 400
    const bad = await uploadCapture(api, user, newCaptureId(), { durationMs: 999_999 })
    expect(bad.res.status()).toBe(400)

    // non-audio content type => 415
    const notAudio = await uploadCapture(api, user, newCaptureId(), { contentType: 'text/plain' })
    expect(notAudio.res.status()).toBe(415)

    // non-canonical UUID => 400
    const badId = await uploadCapture(api, user, 'not-a-uuid')
    expect(badId.res.status()).toBe(400)
  })

  test('STT failure is visible as a typed error and is retryable to success', async () => {
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptSttFailure(api, captureId, 'E2E scripted transient STT outage')

    const up = await uploadCapture(api, user, captureId)
    expect(up.res.status()).toBe(202)

    const failed = await waitTerminal(api, user, captureId)
    expect(failed.status).toBe('failed')
    expect(failed.error_message).toContain('E2E scripted transient STT outage')
    expect(failed.attempt).toBeGreaterThan(0)

    // Client-visible recordings list must expose retryability.
    const list = await (await api.get('/api/recordings', { headers: { Authorization: `Bearer ${user.token}` } })).json()
    const entry = list.find((r: any) => r.capture_id === captureId)
    expect(entry.error_message).toBeTruthy()

    // Re-script the transcript and retry the real job.
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')
    const retry = await api.post(`/api/recordings/${captureId}/retry`, { headers: { Authorization: `Bearer ${user.token}` } })
    expect(retry.status()).toBe(200)
    const retried = await waitTerminal(api, user, captureId)
    expect(retried.status).toBe('ready')
  })

  test('retry on a healthy recording reports the real status (409-free idempotent-ish)', async () => {
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')
    await uploadCapture(api, user, captureId)
    await waitTerminal(api, user, captureId)

    const retry = await api.post(`/api/recordings/${captureId}/retry`, { headers: { Authorization: `Bearer ${user.token}` } })
    expect([409, 200]).toContain(retry.status())
    if (retry.status() === 200) {
      const body = await retry.json()
      expect(['ready', 'queued', 'running', 'completed'].includes(body.status)).toBe(true)
    }
  })

  test('ownership: another account cannot read someone else’s recording', async () => {
    const alice = await createUser(api)
    const bob = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')
    await uploadCapture(api, alice, captureId)

    const status = await api.get(`/api/recordings/${captureId}/status`, {
      headers: { Authorization: `Bearer ${bob.token}` },
    })
    expect([404, 403]).toContain(status.status())

    const audio = await api.get(`/api/recordings/${captureId}/audio`, {
      headers: { Authorization: `Bearer ${bob.token}` },
    })
    expect([404, 403]).toContain(audio.status())
  })

  test('deleting a capture removes recording, knowledge and audio', async () => {
    const user = await createUser(api)
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, 'Echo depends on FastAPI.')
    await uploadCapture(api, user, captureId)
    await waitTerminal(api, user, captureId)

    const del = await api.delete(`/api/captures/${captureId}`, { headers: { Authorization: `Bearer ${user.token}` } })
    expect(del.status()).toBe(200)

    const recordings = await (await api.get('/api/recordings', { headers: { Authorization: `Bearer ${user.token}` } })).json()
    expect(recordings).toHaveLength(0)
    const knowledge = await (await api.get('/api/knowledge', { headers: { Authorization: `Bearer ${user.token}` } })).json()
    expect(knowledge).toHaveLength(0)
    const audio = await api.get(`/api/recordings/${captureId}/audio`, { headers: { Authorization: `Bearer ${user.token}` } })
    expect([404, 403]).toContain(audio.status())
  })

  test('status endpoint for an unknown capture is a clean 404', async () => {
    const user = await createUser(api)
    const res = await api.get(`/api/recordings/${newCaptureId()}/status`, {
      headers: { Authorization: `Bearer ${user.token}` },
    })
    expect([404, 403]).toContain(res.status())
  })
})
