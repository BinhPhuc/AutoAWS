import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getUser: vi.fn(),
  signinSilent: vi.fn(),
  signinRedirectCallback: vi.fn(),
  signinRedirect: vi.fn(),
  clearStaleState: vi.fn(),
  removeUser: vi.fn(),
  settings: null as Record<string, unknown> | null,
}))

vi.mock('oidc-client-ts', async (importOriginal) => {
  const original = await importOriginal<typeof import('oidc-client-ts')>()
  return {
    ...original,
    UserManager: class {
      constructor(settings: Record<string, unknown>) {
        mocks.settings = settings
      }
      getUser = mocks.getUser
      signinSilent = mocks.signinSilent
      signinRedirectCallback = mocks.signinRedirectCallback
      signinRedirect = mocks.signinRedirect
      clearStaleState = mocks.clearStaleState
      removeUser = mocks.removeUser
    },
  }
})

const config = {
  mode: 'cognito',
  issuer: 'https://issuer.example/pool',
  client_id: 'web',
  domain: 'https://login.example',
}
const user = { user_id: 'alice', username: 'Alice' }
let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  mocks.getUser.mockResolvedValue(null)
  window.history.replaceState(null, '', '/')
  sessionStorage.clear()
  localStorage.clear()
  fetchMock = vi.fn(
    async (url: string) =>
      new Response(
        JSON.stringify({
          status_code: 200,
          message: 'OK',
          data: url.endsWith('/config') ? config : user,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
  )
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('Cognito session', () => {
  it('uses code + PKCE with transaction storage and memory-only tokens', async () => {
    const auth = await import('./auth')
    expect(await auth.initializeAuth()).toBeNull()
    expect(mocks.settings).toMatchObject({ response_type: 'code', scope: 'openid email profile' })
    expect(mocks.settings).not.toHaveProperty('disablePKCE', true)
    const store = mocks.settings?.userStore as {
      set: (key: string, value: string) => Promise<void>
    }
    await store.set('test-user', 'sensitive-token')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    await auth.signIn()
    expect(mocks.signinRedirect).toHaveBeenCalledOnce()
  })

  it('consumes callback once and sends access token to the API', async () => {
    window.history.replaceState(null, '', '/auth/callback?code=one-use&state=state')
    mocks.getUser.mockResolvedValue({ access_token: 'access-token', expires_in: 600 })
    const auth = await import('./auth')
    expect(await Promise.all([auth.initializeAuth(), auth.initializeAuth()])).toEqual([user, user])
    expect(mocks.signinRedirectCallback).toHaveBeenCalledOnce()
    expect(window.location.search).toBe('')
    const request = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/me'))
    if (!request) throw new Error('Missing profile request')
    expect(new Headers((request[1] as RequestInit).headers).get('Authorization')).toBe(
      'Bearer access-token',
    )
  })

  it('renews once for concurrent requests', async () => {
    const auth = await import('./auth')
    await auth.initializeAuth()
    mocks.getUser.mockResolvedValue({ access_token: 'expired', expires_in: 0 })
    mocks.signinSilent.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ access_token: 'renewed' }), 10)),
    )
    const { api } = await import('./client')
    await Promise.all([api.get('/api/connections'), api.get('/api/proposals')])
    expect(mocks.signinSilent).toHaveBeenCalledOnce()
    for (const [, init] of fetchMock.mock.calls.slice(1)) {
      expect(new Headers((init as RequestInit).headers).get('Authorization')).toBe('Bearer renewed')
    }
  })

  it('ends session on API 401', async () => {
    const auth = await import('./auth')
    await auth.initializeAuth()
    const ended = vi.fn()
    auth.onSessionEnded(ended)
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ message: 'Authentication required' }), { status: 401 }),
    )
    const { api } = await import('./client')
    await expect(api.get('/api/connections')).rejects.toThrow('Authentication required')
    expect(ended).toHaveBeenCalledOnce()
    expect(mocks.removeUser).toHaveBeenCalled()
  })

  it('clears callback secrets even when state validation fails', async () => {
    window.history.replaceState(null, '', '/auth/callback?code=secret&state=wrong')
    mocks.signinRedirectCallback.mockRejectedValueOnce(new Error('Invalid state'))
    const auth = await import('./auth')
    await expect(auth.initializeAuth()).rejects.toThrow('Invalid state')
    expect(window.location.pathname).toBe('/')
    expect(window.location.search).toBe('')
  })
})
