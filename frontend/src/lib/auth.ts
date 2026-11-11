// Sign-in with the Cognito Hosted UI: OAuth2 authorization code + PKCE, public client
// (docs/API_CONTRACT.md §0.1). No library: the flow is three HTTP calls.
//
// Tokens live in sessionStorage (this tab only, gone when it closes). The API gets the
// access token; the ID token is only read here for the name shown in the header.
import type { AuthConfig } from '@/api/types'

const TOKENS_KEY = 'autoaws.auth.tokens'
const PENDING_KEY = 'autoaws.auth.pending'
const EXPIRY_MARGIN_MS = 60_000

interface Tokens {
  access_token: string
  id_token: string
  refresh_token?: string
  expires_at: number // ms since epoch
}

interface Pending {
  state: string
  verifier: string
  returnTo: string
}

export interface SignedInUser {
  username: string
  email: string | null
}

let config: AuthConfig = { mode: 'none', domain: null, client_id: null, scopes: [] }
let tokens: Tokens | null = read<Tokens>(TOKENS_KEY)
let refreshing: Promise<string | null> | null = null
const listeners = new Set<() => void>()

// ---- storage (may be unavailable: private windows, blocked site data) -------------------

function read<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* the session then lasts until reload */
  }
}

function setTokens(next: Tokens | null) {
  tokens = next
  write(TOKENS_KEY, next)
  listeners.forEach((l) => l())
}

// ---- config ---------------------------------------------------------------------------

/** Leaving the app for the Hosted UI (replaceable in tests). */
export const browser = {
  go: (url: string) => window.location.assign(url),
}

export function setAuthConfig(next: AuthConfig) {
  config = next
}

export function authEnabled(): boolean {
  return config.mode === 'cognito' && !!config.domain && !!config.client_id
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function redirectUri(): string {
  return `${window.location.origin}/auth/callback`
}

// ---- PKCE -----------------------------------------------------------------------------

function base64url(bytes: Uint8Array): string {
  let s = ''
  bytes.forEach((b) => (s += String.fromCharCode(b)))
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomString(bytes = 32): string {
  return base64url(crypto.getRandomValues(new Uint8Array(bytes)))
}

export async function codeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64url(new Uint8Array(digest))
}

// ---- flow -----------------------------------------------------------------------------

/** Go to the Hosted UI; it comes back to /auth/callback. */
export async function signIn(returnTo = window.location.pathname + window.location.search) {
  const pending: Pending = { state: randomString(16), verifier: randomString(48), returnTo }
  write(PENDING_KEY, pending)
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.client_id ?? '',
    redirect_uri: redirectUri(),
    scope: config.scopes.join(' '),
    state: pending.state,
    code_challenge: await codeChallenge(pending.verifier),
    code_challenge_method: 'S256',
  })
  browser.go(`${config.domain}/oauth2/authorize?${params}`)
}

const exchanges = new Map<string, Promise<string>>()

/** Finish the redirect from the Hosted UI. Returns where to go next. Safe to call twice
 * with the same code (StrictMode): the code is exchanged once. */
export function completeSignIn(search: URLSearchParams): Promise<string> {
  const code = search.get('code') ?? ''
  if (!exchanges.has(code)) exchanges.set(code, exchange(search))
  return exchanges.get(code)!
}

async function exchange(search: URLSearchParams): Promise<string> {
  const error = search.get('error_description') || search.get('error')
  if (error) throw new Error(error)
  const pending = read<Pending>(PENDING_KEY)
  const code = search.get('code')
  if (!code || !pending || search.get('state') !== pending.state) {
    throw new Error('The sign-in response does not match this browser tab')
  }
  write(PENDING_KEY, null)
  const body = await tokenRequest({
    grant_type: 'authorization_code',
    client_id: config.client_id ?? '',
    code,
    redirect_uri: redirectUri(),
    code_verifier: pending.verifier,
  })
  setTokens(toTokens(body))
  return pending.returnTo.startsWith('/') && !pending.returnTo.startsWith('//')
    ? pending.returnTo
    : '/'
}

interface TokenResponse {
  access_token: string
  id_token: string
  refresh_token?: string
  expires_in: number
}

async function tokenRequest(form: Record<string, string>): Promise<TokenResponse> {
  const res = await fetch(`${config.domain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(form),
  })
  if (!res.ok) {
    let reason = res.statusText
    try {
      reason = ((await res.json()) as { error?: string }).error ?? reason
    } catch {
      /* not JSON */
    }
    throw new Error(`Token request failed: ${reason}`)
  }
  return (await res.json()) as TokenResponse
}

function toTokens(body: TokenResponse, previous?: Tokens | null): Tokens {
  return {
    access_token: body.access_token,
    id_token: body.id_token ?? previous?.id_token ?? '',
    refresh_token: body.refresh_token ?? previous?.refresh_token,
    expires_at: Date.now() + body.expires_in * 1000,
  }
}

/** A valid access token (refreshed when about to expire), or null: signed out. */
export async function getAccessToken(force = false): Promise<string | null> {
  if (!authEnabled() || !tokens) return null
  if (!force && tokens.expires_at - EXPIRY_MARGIN_MS > Date.now()) return tokens.access_token
  return refresh()
}

function refresh(): Promise<string | null> {
  if (!refreshing) {
    const current = tokens
    refreshing = (async () => {
      if (!current?.refresh_token) {
        setTokens(null)
        return null
      }
      try {
        const body = await tokenRequest({
          grant_type: 'refresh_token',
          client_id: config.client_id ?? '',
          refresh_token: current.refresh_token,
        })
        setTokens(toTokens(body, current))
        return tokens?.access_token ?? null
      } catch {
        setTokens(null) // refresh token expired or revoked: sign in again
        return null
      }
    })().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

/** The API refused the token: drop it (the app shows the sign-in page). */
export function clearSession() {
  setTokens(null)
}

export function signOut() {
  setTokens(null)
  const params = new URLSearchParams({
    client_id: config.client_id ?? '',
    logout_uri: `${window.location.origin}/`,
  })
  browser.go(`${config.domain}/logout?${params}`)
}

export function isSignedIn(): boolean {
  return !!tokens
}

/** Name to show: from the ID token (already trusted: it came from the token endpoint). */
export function currentUser(): SignedInUser | null {
  if (!tokens?.id_token) return null
  try {
    const part = tokens.id_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const bytes = Uint8Array.from(atob(part), (c) => c.charCodeAt(0))
    const claims = JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>
    const email = typeof claims.email === 'string' ? claims.email : null
    const username = String(claims['cognito:username'] ?? email ?? claims.sub ?? '')
    return { username, email }
  } catch {
    return null
  }
}
