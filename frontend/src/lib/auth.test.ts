import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/api/client'
import * as auth from './auth'

const DOMAIN = 'https://autodiag-test.auth.ap-southeast-1.amazoncognito.com'

function jwtWith(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, '')
  return `${b64({ alg: 'RS256' })}.${b64(claims)}.sig`
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

let go: ReturnType<typeof vi.fn>
let codes = 0

beforeEach(() => {
  sessionStorage.clear()
  auth.clearSession()
  auth.setAuthConfig({
    mode: 'cognito',
    domain: DOMAIN,
    client_id: 'web123',
    scopes: ['openid', 'email', 'profile'],
  })
  go = vi.fn()
  auth.browser.go = go as unknown as (url: string) => void
})

afterEach(() => vi.unstubAllGlobals())

async function signInWithCode(fetchMock: ReturnType<typeof vi.fn>, expiresIn = 3600) {
  await auth.signIn('/proposals')
  const url = new URL(go.mock.calls[0][0] as string)
  fetchMock.mockResolvedValueOnce(
    json({
      access_token: 'access-1',
      id_token: jwtWith({ email: 'minh@example.com', 'cognito:username': 'u-1' }),
      refresh_token: 'refresh-1',
      expires_in: expiresIn,
    }),
  )
  const code = `code-${++codes}` // one exchange per code (StrictMode guard)
  const params = new URLSearchParams({ code, state: url.searchParams.get('state')! })
  return { url, next: await auth.completeSignIn(params) }
}

describe('sign-in (authorization code + PKCE)', () => {
  it('sends the user to the Hosted UI with an S256 challenge', async () => {
    await auth.signIn('/chat')
    const url = new URL(go.mock.calls[0][0] as string)
    expect(url.origin + url.pathname).toBe(`${DOMAIN}/oauth2/authorize`)
    expect(url.searchParams.get('response_type')).toBe('code')
    expect(url.searchParams.get('client_id')).toBe('web123')
    expect(url.searchParams.get('redirect_uri')).toBe(`${window.location.origin}/auth/callback`)
    expect(url.searchParams.get('scope')).toBe('openid email profile')
    expect(url.searchParams.get('code_challenge_method')).toBe('S256')
    const pending = JSON.parse(sessionStorage.getItem('autoaws.auth.pending')!)
    expect(url.searchParams.get('state')).toBe(pending.state)
    expect(url.searchParams.get('code_challenge')).toBe(await auth.codeChallenge(pending.verifier))
  })

  it('exchanges the code with the verifier and remembers the user', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { next } = await signInWithCode(fetchMock)
    expect(next).toBe('/proposals')
    const [tokenUrl, init] = fetchMock.mock.calls[0]
    expect(tokenUrl).toBe(`${DOMAIN}/oauth2/token`)
    const form = new URLSearchParams(String(init.body))
    expect(form.get('grant_type')).toBe('authorization_code')
    expect(form.get('code')).toMatch(/^code-\d+$/)
    expect(form.get('code_verifier')).toBeTruthy()
    expect(auth.isSignedIn()).toBe(true)
    expect(auth.currentUser()).toEqual({ username: 'u-1', email: 'minh@example.com' })
    expect(await auth.getAccessToken()).toBe('access-1')
  })

  it('refuses a response that does not belong to this tab', async () => {
    await auth.signIn('/')
    const params = new URLSearchParams({ code: 'code-x', state: 'someone-elses-state' })
    await expect(auth.completeSignIn(params)).rejects.toThrow(/does not match/)
    expect(auth.isSignedIn()).toBe(false)
  })

  it('shows the error the Hosted UI returned', async () => {
    const params = new URLSearchParams({ error: 'access_denied', error_description: 'Denied' })
    await expect(auth.completeSignIn(params)).rejects.toThrow('Denied')
  })
})

describe('tokens', () => {
  it('refreshes an access token that is about to expire', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await signInWithCode(fetchMock, 30) // expires within the margin
    fetchMock.mockResolvedValueOnce(json({ access_token: 'access-2', expires_in: 3600 }))
    expect(await auth.getAccessToken()).toBe('access-2')
    const form = new URLSearchParams(String(fetchMock.mock.calls[1][1].body))
    expect(form.get('grant_type')).toBe('refresh_token')
    expect(form.get('refresh_token')).toBe('refresh-1')
    expect(auth.currentUser()?.email).toBe('minh@example.com') // ID token kept
  })

  it('signs out locally when the refresh token is refused', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await signInWithCode(fetchMock, 30)
    fetchMock.mockResolvedValueOnce(json({ error: 'invalid_grant' }, 400))
    expect(await auth.getAccessToken()).toBeNull()
    expect(auth.isSignedIn()).toBe(false)
  })

  it('sign out clears the session and ends the Hosted UI session', () => {
    auth.signOut()
    const url = new URL(go.mock.calls[0][0] as string)
    expect(url.origin + url.pathname).toBe(`${DOMAIN}/logout`)
    expect(url.searchParams.get('logout_uri')).toBe(`${window.location.origin}/`)
  })
})

describe('API calls', () => {
  it('send the access token, and retry once with a fresh one after a 401', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await signInWithCode(fetchMock)
    fetchMock
      .mockResolvedValueOnce(json({ status_code: 401, message: 'x', error: 'UNAUTHORIZED' }, 401))
      .mockResolvedValueOnce(json({ access_token: 'access-2', expires_in: 3600 })) // refresh
      .mockResolvedValueOnce(json({ status_code: 200, message: 'OK', data: { ok: 1 } }))
    const result = await apiFetch<{ ok: number }>('/api/me')
    expect(result.data).toEqual({ ok: 1 })
    const auths = fetchMock.mock.calls
      .filter(([u]) => String(u).endsWith('/api/me'))
      .map(([, init]) => new Headers(init.headers).get('Authorization'))
    expect(auths).toEqual(['Bearer access-1', 'Bearer access-2'])
  })

  it('without sign-in (AUTH_MODE=none) send no token', async () => {
    auth.setAuthConfig({ mode: 'none', domain: null, client_id: null, scopes: [] })
    const fetchMock = vi.fn().mockResolvedValue(json({ status_code: 200, message: 'OK', data: 1 }))
    vi.stubGlobal('fetch', fetchMock)
    await apiFetch('/api/connections')
    expect(new Headers(fetchMock.mock.calls[0][1].headers).has('Authorization')).toBe(false)
  })
})
