import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts'
import { api, configureAuthentication } from './client'
import type { AuthConfig, AuthUser } from './types'

let manager: UserManager | null = null
let config: AuthConfig | null = null
let initialization: Promise<AuthUser | null> | null = null
let renewal: Promise<string | null> | null = null
const listeners = new Set<() => void>()

export function onSessionEnded(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function sessionEnded() {
  void manager?.removeUser()
  listeners.forEach((listener) => listener())
}

async function accessToken(): Promise<string | null> {
  if (!manager) return null
  const user = await manager.getUser()
  if (!user) return null
  if ((user.expires_in ?? 0) > 30) return user.access_token
  renewal ??= manager
    .signinSilent()
    .then((fresh) => fresh?.access_token ?? null)
    .catch(() => {
      sessionEnded()
      return null
    })
    .finally(() => {
      renewal = null
    })
  return renewal
}

async function initialize(): Promise<AuthUser | null> {
  config = (await api.get<AuthConfig>('/api/auth/config')).data
  if (config.mode === 'none') return (await api.get<AuthUser>('/api/auth/me')).data
  if (!config.issuer || !config.client_id || !config.domain) throw new Error('Invalid auth config')
  manager = new UserManager({
    authority: config.issuer,
    client_id: config.client_id,
    redirect_uri: `${window.location.origin}/auth/callback`,
    response_type: 'code',
    scope: 'openid email profile',
    // Only the PKCE transaction survives the login redirect. Tokens stay in memory.
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    automaticSilentRenew: false,
    loadUserInfo: false,
    metadata: {
      issuer: config.issuer,
      authorization_endpoint: `${config.domain}/oauth2/authorize`,
      token_endpoint: `${config.domain}/oauth2/token`,
      jwks_uri: `${config.issuer}/.well-known/jwks.json`,
      revocation_endpoint: `${config.domain}/oauth2/revoke`,
    },
  })
  configureAuthentication(accessToken, sessionEnded)
  if (window.location.pathname !== '/auth/callback') return null
  try {
    await manager.signinRedirectCallback()
    return (await api.get<AuthUser>('/api/auth/me')).data
  } finally {
    // Remove the one-use code and state from history, including failed callbacks.
    window.history.replaceState(null, '', '/')
  }
}

export function initializeAuth() {
  initialization ??= initialize()
  return initialization
}

export async function signIn() {
  await manager?.clearStaleState()
  await manager?.signinRedirect()
}

export async function signOut() {
  // Always clear local state, including when the revocation endpoint is unavailable.
  try {
    await manager?.revokeTokens(['refresh_token'])
  } finally {
    await manager?.removeUser()
    sessionEnded()
    if (config?.domain && config.client_id) {
      const params = new URLSearchParams({
        client_id: config.client_id,
        logout_uri: window.location.origin,
      })
      window.location.assign(`${config.domain}/logout?${params}`)
    }
  }
}
