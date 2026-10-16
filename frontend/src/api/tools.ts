import { api } from './client'
import type { Health, ToolSpec } from './types'

export const toolsApi = {
  list: () => api.get<ToolSpec[]>('/api/tools'),
}

export const healthApi = {
  get: () => api.get<Health>('/api/health'),
}
