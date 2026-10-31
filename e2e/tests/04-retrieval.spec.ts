import { test, expect } from '@playwright/test'
import {
  createClient,
  createUser,
  newCaptureId,
  scriptTranscript,
  uploadCapture,
  waitTerminal,
} from '../helpers/harness'

interface EchoUser {
  email: string
  password: string
  token: string
  userId: string
}

/**
 * "Note synchronization" at the API level: this is what the mobile app does
 * when it (re)connects — fetches /api/knowledge, opens items, runs semantic
 * search, verifies provenance. The mobile device flow itself is verified
 * separately (see the run report); these tests pin the contract the app
 * deduplicates against.
 */
test.describe('Retrieval & knowledge sync API (mobile client replica)', () => {
  let api: Awaited<ReturnType<typeof createClient>>

  test.beforeAll(async () => {
    api = await createClient()
  })
  test.afterAll(async () => {
    await api.dispose()
  })

  async function ingestMany(user: EchoUser, transcripts: string[]): Promise<string[]> {
    const ids: string[] = []
    for (const transcript of transcripts) {
      const captureId = newCaptureId()
      await scriptTranscript(api, captureId, transcript)
      const up = await uploadCapture(api, user, captureId)
      expect(up.res.status()).toBe(202)
      const job = await waitTerminal(api, user, captureId)
      expect(job.status).toBe('ready')
      ids.push(captureId)
    }
    return ids
  }

  test('knowledge list sync returns extracted items with stable ids after re-fetch', async () => {
    const user = await createUser(api)
    await ingestMany(user, [
      'Echo depends on FastAPI.',
      'Flutter uses the Riverpod linter rules. Postgres stores captured voices.',
    ])

    const url = '/api/knowledge'
    const first = await api.get(url, { headers: { Authorization: `Bearer ${user.token}` } })
    const second = await api.get(url, { headers: { Authorization: `Bearer ${user.token}` } })
    expect(first.ok() && second.ok()).toBeTruthy()
    const a = await first.json()
    const b = await second.json()
    expect(a).toHaveLength(2)
    expect(b).toHaveLength(2)
    // Stable, idempotent reads: two sync passes agree exactly (PRC-04 dedup).
    expect(b.map((x: any) => x.id)).toEqual(a.map((x: any) => x.id))
    for (const item of a) {
      expect(item.capture_id).toBeTruthy()
      expect(item.title).toBeTruthy()
      expect(item.core_idea).toBeTruthy()
      expect(item.provenance).toBe('voice-capture')
      // No transcript field exists on the public schema at all.
      expect(item.transcript).toBeUndefined()
    }
  })

  test('item detail returns the full public record', async () => {
    const user = await createUser(api)
    await ingestMany(user, ['Echo depends on FastAPI.'])
    const list = await (await api.get('/api/knowledge', { headers: { Authorization: `Bearer ${user.token}` } })).json()
    const id = list[0].id

    const detail = await api.get(`/api/knowledge/${id}`, { headers: { Authorization: `Bearer ${user.token}` } })
    expect(detail.status()).toBe(200)
    expect((await detail.json()).id).toBe(id)

    const other = await createUser(api)
    const cross = await api.get(`/api/knowledge/${id}`, { headers: { Authorization: `Bearer ${other.token}` } })
    expect([404, 403]).toContain(cross.status())
  })

  test('semantic search ranks the most relevant item first (cohorts)', async () => {
    const user = await createUser(api)
    await ingestMany(user, [
      'Echo depends on FastAPI for its voice pipeline.',
      'Groceries today: buy apples near the market and check the river level.',
    ])

    const res = await api.get(
      '/api/knowledge/semantic-search?q=voice pipeline fastapi&limit=5',
      { headers: { Authorization: `Bearer ${user.token}` } },
    )
    expect(res.ok()).toBeTruthy()
    const scored = (await res.json()) as Array<{ item: any; similarity_score: number }>
    expect(scored.length).toBeGreaterThan(0)
    // Hybrid search: the FastAPI recording should be the top hit.
    expect(scored[0].item.core_idea.toLowerCase()).toContain('fastapi')
    for (const s of scored) {
      expect(s.similarity_score).toBeGreaterThanOrEqual(0)
    }
  })

  test('semantically unrelated query still returns documented shape', async () => {
    const user = await createUser(api)
    await ingestMany(user, ['Echo depends on FastAPI.'])
    const res = await api.get('/api/knowledge/semantic-search?q=zzz%20unrelated%20quantum&limit=5', {
      headers: { Authorization: `Bearer ${user.token}` },
    })
    expect(res.ok()).toBeTruthy()
    const scored = await res.json()
    expect(Array.isArray(scored)).toBe(true)
    for (const s of scored) {
      expect(typeof s.similarity_score).toBe('number')
    }
  })

  test('providers endpoint discloses who sees what (privacy contract)', async () => {
    const user = await createUser(api)
    const res = await api.get('/api/providers', { headers: { Authorization: `Bearer ${user.token}` } })
    expect(res.ok()).toBeTruthy()
    const providers = await res.json()
    const ids = new Set(providers.map((p: any) => p.id))
    expect(providers.length).toBeGreaterThan(0)
    for (const p of providers) {
      expect(p.trains_on_data).toBeDefined()
      expect(p.id).toBeTruthy()
      expect(p.retention || p.detail).toBeTruthy()
    }
  })
})
