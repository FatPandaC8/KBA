import { test, expect } from '@playwright/test'
import { createClient, createUser, h } from '../helpers/harness'

test.describe('Authentication & account lifecycle (real HTTP flows)', () => {
  let api: Awaited<ReturnType<typeof createClient>>

  test.beforeAll(async () => {
    api = await createClient()
  })

  test.afterAll(async () => {
    await api.dispose()
  })

  test('signup → verify → login → /me returns the verified identity', async () => {
    const email = `auth-ok-${Date.now()}@e2e.example.com`
    const password = 'E2ePassword!234'

    const signup = await api.post('/api/auth/signup', { data: { email, password } })
    expect(signup.status()).toBe(200)
    const { dev_verification_token } = await signup.json()
    expect(dev_verification_token).toBeTruthy()

    const verify = await api.post('/api/auth/verify-email', { data: { token: dev_verification_token } })
    expect(verify.status()).toBe(200)

    const login = await api.post('/api/auth/login', { data: { email, password } })
    expect(login.status()).toBe(200)
    const session = await login.json()
    expect(session.token).toBeTruthy()
    expect(session.user.email).toBe(email)
    expect(session.user.email_verified).toBe(true)

    const me = await api.get('/api/auth/me', { headers: h(session.token) })
    expect(me.status()).toBe(200)
    expect((await me.json()).id).toBe(session.user.id)
  })

  test('wrong password is rejected with 401', async () => {
    const user = await createUser(api)
    const res = await api.post('/api/auth/login', {
      data: { email: user.email, password: 'WrongPassword!555' },
    })
    expect(res.status()).toBe(401)
  })

  test('duplicate signup cannot enumerate or create accounts', async () => {
    const user = await createUser(api)
    const dup = await api.post('/api/auth/signup', { data: { email: user.email, password: 'Whatever!123' } })
    expect(dup.status()).toBe(200)
    const body = await dup.json()
    // Generic response: verification material must NOT be handed out again.
    expect(body.dev_verification_token).toBeFalsy()
  })

  test('unverified account authenticates but is blocked from creating records', async () => {
    const email = `auth-unverified-${Date.now()}@e2e.example.com`
    const password = 'E2ePassword!234'
    const signup = await api.post('/api/auth/signup', { data: { email, password } })
    // Do NOT verify the email.
    expect(signup.ok()).toBeTruthy()

    const login = await api.post('/api/auth/login', { data: { email, password } })
    expect(login.status()).toBe(200)
    const { token } = await login.json()

    const knowledge = await api.get('/api/knowledge', { headers: h(token) })
    expect(knowledge.status()).toBe(403)

    const captureId = crypto.randomUUID()
    const upload = await api.post('/api/captures/upload', {
      headers: h(token),
      multipart: {
        file: { name: 'c.m4a', mimeType: 'audio/mp4', buffer: Buffer.alloc(512, 1) },
        capture_id: captureId,
        idempotency_key: captureId,
        duration_ms: '2000',
      },
    })
    expect(upload.status()).toBe(403)
  })

  test('records are blocked until consent is granted (consent gate)', async () => {
    const user = await createUser(api, true)
    // Revoke consent -> consent gate must fail closed.
    const revoke = await api.post('/api/consent', { headers: h(user.token), data: { granted: false } })
    expect(revoke.ok()).toBeTruthy()

    const captureId = crypto.randomUUID()
    const upload = await api.post('/api/captures/upload', {
      headers: h(user.token),
      multipart: {
        file: { name: 'c.m4a', mimeType: 'audio/mp4', buffer: Buffer.alloc(512, 2) },
        capture_id: captureId,
        idempotency_key: captureId,
        duration_ms: '2000',
      },
    })
    expect(upload.status()).toBe(403)

    const graph = await api.get('/api/graph', { headers: h(user.token) })
    expect(graph.status()).toBe(403)
  })

  test('logout revokes the session token', async () => {
    const user = await createUser(api)
    const logout = await api.post('/api/auth/logout', { headers: h(user.token) })
    expect(logout.ok()).toBeTruthy()

    const after = await api.get('/api/auth/me', { headers: h(user.token) })
    expect(after.status()).toBe(401)
  })

  test('account deletion removes the user and revokes sessions', async () => {
    const user = await createUser(api)
    const del = await api.delete('/api/account?confirm=DELETE', { headers: h(user.token) })
    expect(del.status()).toBe(200)
    expect((await del.json()).deleted).toBe(true)

    const after = await api.get('/api/auth/me', { headers: h(user.token) })
    expect(after.status()).toBe(401)
    const relogin = await api.post('/api/auth/login', {
      data: { email: user.email, password: user.password },
    })
    expect(relogin.status()).toBe(401)
  })

  test('missing or garbage bearer tokens are rejected 401', async () => {
    expect((await api.get('/api/recordings')).status()).toBe(401)
    expect((await api.get('/api/recordings', { headers: h('not-a-real-session') })).status()).toBe(401)
  })
})
