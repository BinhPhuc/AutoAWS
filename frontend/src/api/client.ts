import type { ApiErrorBody, Envelope } from './types'

export const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  status_code: number
  error: string
  path: string
  timestamp: string

  constructor(body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status_code = body.status_code
    this.error = body.error
    this.path = body.path
    this.timestamp = body.timestamp
  }
}

export interface ApiResult<T> {
  data: T
  message: string
}

/** Builds a fallback error body when the server did not return the standard error JSON. */
function fallbackError(res: Response, path: string): ApiErrorBody {
  return {
    status_code: res.status,
    message: res.statusText || 'Request failed',
    error: res.status >= 500 ? 'INTERNAL' : 'VALIDATION_ERROR',
    path,
    timestamp: new Date().toISOString(),
  }
}

export async function toApiError(res: Response, path: string): Promise<ApiError> {
  let body: ApiErrorBody
  try {
    body = (await res.json()) as ApiErrorBody
    if (typeof body?.message !== 'string') body = fallbackError(res, path)
  } catch {
    body = fallbackError(res, path)
  }
  return new ApiError(body)
}

/** Fetch wrapper: JSON in/out, unwraps the success envelope, throws ApiError on failure. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  headers.set('Accept', 'application/json')

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  } catch (err) {
    throw new ApiError({
      status_code: 0,
      message: err instanceof Error ? err.message : 'Network error',
      error: 'NETWORK_ERROR',
      path,
      timestamp: new Date().toISOString(),
    })
  }
  if (!res.ok) throw await toApiError(res, path)

  const body = (await res.json()) as Envelope<T>
  return { data: body.data, message: body.message }
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
}
