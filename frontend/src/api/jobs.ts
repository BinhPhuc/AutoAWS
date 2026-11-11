import { api } from './client'
import type { Job } from './types'

export const jobsApi = {
  /** `after`: only events with a larger `seq` (the ones the client does not have yet). */
  get: (id: string, after = -1) => api.get<Job>(`/api/jobs/${id}?after=${after}`),
  cancel: (id: string) => api.post<Job>(`/api/jobs/${id}/cancel`),
}
