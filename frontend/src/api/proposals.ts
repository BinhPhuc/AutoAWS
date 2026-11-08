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
  actions: () => api.get<RemediationAction[]>('/api/remediation/actions'),
}
