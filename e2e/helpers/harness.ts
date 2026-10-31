import { APIRequestContext, expect, request, type Page } from '@playwright/test'

export const BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8123'
export const ADMIN_TOKEN = process.env.E2E_ADMIN_TOKEN || 'e2e-admin-token-not-a-real-credential'
export const E2E_KEY = process.env.E2E_KEY || 'e2e-harness-key'
export const DB_PATH = process.env.E2E_WORKDIR || '/tmp/opencode/echo-e2e'

export function adminHeaders(extra: Record<string, string> = {}) {
  return { Authorization: `Bearer ${ADMIN_TOKEN}`, ...extra }
}

export function h(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` }
}

export async function createClient(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE_URL, timeout: 30_000 })
}

export interface EchoUser {
  email: string
  password: string
  token: string
  userId: string
}

let seq = 0

/** Full, real signup → verify → login → consent flow, all over HTTP. */
export async function createUser(api: APIRequestContext, consent = true): Promise<EchoUser> {
  seq += 1
  const email = `e2e-user-${Date.now()}-${seq}-${Math.random().toString(36).slice(2, 8)}@e2e.example.com`
  const password = 'E2ePassword!234'

  const signup = await api.post('/api/auth/signup', {
    data: { email, password },
  })
  expect(signup.ok(), `signup for ${email}: ${signup.status()} ${await signup.text()}`).toBeTruthy()
  const { dev_verification_token: devToken } = await signup.json()
  expect(devToken, 'test env must expose the dev verification token').toBeTruthy()

  const verify = await api.post('/api/auth/verify-email', { data: { token: devToken } })
  expect(verify.ok()).toBeTruthy()

  const login = await api.post('/api/auth/login', { data: { email, password } })
  expect(login.ok(), `login: ${login.status()} ${await login.text()}`).toBeTruthy()
  const body = await login.json()

  if (consent) {
    const granted = await api.post('/api/consent', {
      data: { granted: true },
      headers: h(body.token),
    })
    expect(granted.ok(), `consent: ${granted.status()} ${await granted.text()}`).toBeTruthy()
  }
  return { email, password, token: body.token, userId: body.user.id }
}

/** Register the deterministic transcript the fake STT must return for a capture. */
export async function scriptTranscript(
  api: APIRequestContext,
  captureId: string,
  text: string,
): Promise<void> {
  const res = await api.post('/__e2e__/script', {
    headers: { 'x-e2e-key': E2E_KEY },
    data: { captureId, text },
  })
  expect(res.ok(), `script STT: ${res.status()} ${await res.text()}`).toBeTruthy()
}

/** Register a scripted STT failure (real error path through the job pipeline). */
export async function scriptSttFailure(
  api: APIRequestContext,
  captureId: string,
  error = 'E2E scripted transient STT failure',
): Promise<void> {
  const res = await api.post('/__e2e__/script', {
    headers: { 'x-e2e-key': E2E_KEY },
    data: { captureId, text: '', fail: true, error },
  })
  expect(res.ok()).toBeTruthy()
}

export interface UploadOptions {
  durationMs?: number
  mimeType?: string
  contentType?: string
}

/** Multipart upload mirroring exactly what the mobile client sends. */
export async function uploadCapture(
  api: APIRequestContext,
  user: EchoUser,
  captureId: string,
  opts: UploadOptions = {},
): Promise<{ res: Awaited<ReturnType<APIRequestContext['post']>>; body: any }> {
  const audio = Buffer.alloc(2048, 0x00)
  const res = await api.post('/api/captures/upload', {
    headers: h(user.token),
    multipart: {
      file: {
        name: 'capture.m4a',
        mimeType: opts.contentType ?? 'audio/mp4',
        buffer: audio,
      },
      capture_id: captureId,
      idempotency_key: captureId,
      duration_ms: String(opts.durationMs ?? 2000),
    },
  })
  let body: any = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  return { res, body }
}

export function newCaptureId(): string {
  return crypto.randomUUID()
}

/** Poll the real job endpoint until a predicate over the status body holds. */
export async function waitForJob(
  api: APIRequestContext,
  user: EchoUser,
  captureId: string,
  predicate: (body: any) => boolean,
  timeoutMs = 30_000,
): Promise<any> {
  const headers = h(user.token)
  const deadline = Date.now() + timeoutMs
  let last: any = null
  while (Date.now() < deadline) {
    const res = await api.get(`/api/recordings/${captureId}/status`, { headers })
    last = await res.json()
    if (predicate(last)) {
      return last
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error(
    `job ${captureId} never reached the desired state within ${timeoutMs}ms; last status: ${JSON.stringify(last)}`,
  )
}

/** Wait until the worker reached a terminal state; returns the final status. */
export async function waitTerminal(
  api: APIRequestContext,
  user: EchoUser,
  captureId: string,
  timeoutMs = 30_000,
): Promise<any> {
  return waitForJob(
    api,
    user,
    captureId,
    (b) => ['ready', 'failed', 'completed'].includes(b.status) || b.stage === 'completed',
    timeoutMs,
  )
}

export function newToken(): string {
  return `tok-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/** Console/page error listener for browser tests. */
export function trackErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  return errors
}
