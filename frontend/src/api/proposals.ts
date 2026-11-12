import { api } from './client'
import type { Decision, DecisionResult, Proposal, RemediationAction } from './types'

export const proposalsApi = {
  list: (params: { conversation_id?: string; status?: string } = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][],
    ).toString()
    return api.get<Proposal[]>(`/api/proposals${q ? `?${q}` : ''}`)
  },
  get: (id: string) => api.get<Proposal>(`/api/proposals/${id}`),
  decide: (id: string, decision: Decision, feedback = '') =>
    api.post<DecisionResult>(`/api/proposals/${id}/decision`, { decision, feedback }),
  /** Edited parameters -> a NEW proposal to review (the old one, if pending, is superseded). */
  revise: (id: string, params: Record<string, unknown>) =>
    api.post<Proposal>(`/api/proposals/${id}/revise`, { params }),
  actions: () => api.get<RemediationAction[]>('/api/remediation/actions'),
}
