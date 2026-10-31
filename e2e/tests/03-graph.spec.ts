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

test.describe('Knowledge graph: normalization, browsing, entity management', () => {
  let api: Awaited<ReturnType<typeof createClient>>
  let user: EchoUser
  const token = () => ({ Authorization: `Bearer ${user.token}` })

  test.beforeAll(async () => {
    api = await createClient()
  })
  test.beforeEach(async () => {
    user = await createUser(api)
  })
  test.afterAll(async () => {
    await api.dispose()
  })

  async function ingest(transcript: string): Promise<string> {
    const captureId = newCaptureId()
    await scriptTranscript(api, captureId, transcript)
    const up = await uploadCapture(api, user, captureId)
    expect(up.res.status()).toBe(202)
    const job = await waitTerminal(api, user, captureId)
    expect(job.status, JSON.stringify(job)).toBe('ready')
    return captureId
  }

  async function graph(): Promise<any> {
    const res = await api.get('/api/graph', { headers: token() })
    expect(res.ok()).toBeTruthy()
    return res.json()
  }

  test('relationship normalization: alias maps to canonical type; novel meaning gets its own entry', async () => {
    await ingest('Echo depends on FastAPI.')
    await ingest('Echo relies on FastAPI.')
    await ingest('Echo works at Acme with Alice.')

    const edges = (await graph()).edges as any[]
    const types = edges.map((e) => e.type)
    expect(types).toContain('Depends on') // "relies on" normalised to canonical alias
    expect(types).toContain('Works at') // open-ended speech cue -> new registry entry
  })

  test('graph browsing: nodes carry entity kinds and degrees; evidence is exposed on edges', async () => {
    await ingest('Echo depends on FastAPI.')

    const g = await graph()
    const titles = (g.nodes as any[]).map((n) => n.title.toLowerCase())
    expect(titles).toContain('echo')
    expect(titles).toContain('fastapi')
    expect(g.edges.length).toBeGreaterThan(0)

    const kinds = (g.nodes as any[]).map((n) => n.kind)
    expect(kinds).toContain('tool') // FastAPI must be detected as a tool entity

    // Evidence text persisted with the relationship (traceability).
    const dependsEdge = (g.edges as any[]).find((e) => e.type === 'Depends on')
    expect(dependsEdge).toBeTruthy()
    expect((dependsEdge.evidence || '').toLowerCase()).toContain('depends on')

    // Nodes form a real graph: each edge references existing node ids.
    const ids = new Set((g.nodes as any[]).map((n) => n.id))
    for (const e of g.edges) {
      expect(ids.has(e.from_node)).toBe(true)
      expect(ids.has(e.to_node)).toBe(true)
    }
  })

  test('same entity mentioned across two captures is resolved to one node', async () => {
    await ingest('I met Alice about the Echo project. Echo depends on FastAPI.')
    await ingest('I asked Alice whether the Echo project works fine.')

    const g = await graph()
    const echoNodes = (g.nodes as any[]).filter((n) => n.title.toLowerCase() === 'echo')
    expect(echoNodes.length).toBe(1)
    const aliceNodes = (g.nodes as any[]).filter((n) => n.title.toLowerCase() === 'alice')
    expect(aliceNodes.length).toBe(1)

    // Echo's degree reflects cross-capture evidence.
    const echoNode = echoNodes[0]
    expect(echoNode.degree).toBeGreaterThan(0)
  })

  test('entity detail exposes relationships, names and user PATCH persists', async () => {
    await ingest('Echo depends on FastAPI.')

    const g = await graph()
    const echoNode = (g.nodes as any[]).find((n) => n.title.toLowerCase() === 'echo')
    expect(echoNode).toBeTruthy()

    const detail = await api.get(`/api/graph/entities/${echoNode.id}`, { headers: token() })
    expect(detail.status()).toBe(200)
    const d = await detail.json()
    expect(d.entity.id).toBe(echoNode.id)
    expect(d.relationships.length).toBeGreaterThan(0)

    // Client-side rename must persist...
    const patch = await api.patch(`/api/graph/entities/${echoNode.id}`, {
      headers: token(),
      data: { name: 'Echo (knowledge base)' },
    })
    expect(patch.status()).toBe(200)
    expect((await patch.json()).name).toBe('Echo (knowledge base)')

    const detail2 = await api.get(`/api/graph/entities/${echoNode.id}`, { headers: token() })
    const d2 = await detail2.json()
    expect(d2.entity.name).toBe('Echo (knowledge base)')

    const g2 = await graph()
    const after = await (g2.nodes as any[]).find((n) => n.id === echoNode.id)
    expect(after.title).toBe('Echo (knowledge base)')

    // ...and mobile-style reverting stays available (second PATCH).
    const patchBack = await api.patch(`/api/graph/entities/${echoNode.id}`, {
      headers: token(),
      data: { name: 'Echo' },
    })
    expect(patchBack.status()).toBe(200)
  })

  test('entity delete removes node and its edges from the graph', async () => {
    await ingest('Echo depends on FastAPI.')
    const g = await graph()
    const fastapi = (g.nodes as any[]).find((n) => n.title.toLowerCase() === 'fastapi')
    expect(fastapi).toBeTruthy()

    const del = await api.delete(`/api/graph/entities/${fastapi.id}`, { headers: token() })
    expect(del.status()).toBe(200)

    const g2 = await graph()
    expect((g2.nodes as any[]).find((n) => n.id === fastapi.id)).toBeFalsy()
    // Edge vanished with the node.
    const attached = (g2.edges as any[]).filter((e) => e.from_node === fastapi.id || e.to_node === fastapi.id)
    expect(attached).toHaveLength(0)
  })

  test('relationship status can be confirmed and rejected via the mobile-style endpoint', async () => {
    await ingest('Echo depends on FastAPI.')
    const g = await graph()
    const edge = (g.edges as any[])[0]
    expect(edge).toBeTruthy()

    const confirm = await api.patch(`/api/relationships/${edge.id}?status=confirmed`, { headers: token() })
    expect(confirm.status()).toBe(200)
    expect((await confirm.json()).status).toBe('confirmed')

    const g2 = await graph()
    const updated = (g2.edges as any[]).find((e) => e.id === edge.id)
    expect(updated.status).toBe('confirmed')

    const reject = await api.patch(`/api/relationships/${edge.id}?status=rejected`, { headers: token() })
    expect(reject.status()).toBe(200)
    const g3 = await graph()
    const rejected = (g3.edges as any[]).find((e) => e.id === edge.id)
    expect(rejected.status).toBe('rejected')

    const removed = await api.delete(`/api/relationships/${edge.id}`, { headers: token() })
    expect(removed.status()).toBe(200)
    const g4 = await graph()
    expect((g4.edges as any[]).find((e) => e.id === edge.id)).toBeFalsy()
  })

  test('graph ownership: another account sees only its own graph', async () => {
    const mine = await ingest('Echo depends on FastAPI and Postgres.')

    const other = await createUser(api)
    const res = await api.get('/api/graph', { headers: { Authorization: `Bearer ${other.token}` } })
    const otherGraph = await res.json()
    expect(otherGraph.nodes).toHaveLength(0)
    expect(otherGraph.edges).toHaveLength(0)

    // My graph still has my data.
    const minePost = await api.get('/api/graph/search?q=Echo&limit=20', { headers: token() })
    expect(((await minePost.json()).entities as any[]).length).toBeGreaterThan(0)
  })
})
