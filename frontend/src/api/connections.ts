import { api } from './client'
import type { CloudFormationInfo, Connection, CreateConnectionInput, VerifyResult } from './types'

export const connectionsApi = {
  list: () => api.get<Connection[]>('/api/connections'),
  get: (id: string) => api.get<Connection>(`/api/connections/${id}`),
  create: (input: CreateConnectionInput) => api.post<Connection>('/api/connections', input),
  setRemediationRole: (id: string, remediation_role_arn: string | null) =>
    api.patch<Connection>(`/api/connections/${id}`, { remediation_role_arn }),
  remove: (id: string) => api.delete<null>(`/api/connections/${id}`),
  verify: (id: string) => api.post<VerifyResult>(`/api/connections/${id}/verify`),
  cloudformation: (id: string) =>
    api.get<CloudFormationInfo>(`/api/connections/${id}/cloudformation`),
}
