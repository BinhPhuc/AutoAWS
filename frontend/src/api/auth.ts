import { api } from './client'
import type { AuthConfig, Me } from './types'

export const authApi = {
  /** Public: how this deployment signs users in. */
  config: () => api.get<AuthConfig>('/api/auth/config'),
  me: () => api.get<Me>('/api/me'),
}
