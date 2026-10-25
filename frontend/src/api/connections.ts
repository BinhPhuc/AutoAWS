import { api } from './client'
import type {
  CloudFormationInfo,
  ConnectionSetup,
  Connection,
  CreateConnectionInput,
  VerifyResult,
} from './types'

export const connectionsApi = {
  cloudformationPreview: (externalId: string) =>
    api.post<CloudFormationInfo>('/api/connections/cloudformation-preview', {
      external_id: externalId,
    }),
  setup: () => api.get<ConnectionSetup>('/api/connections/setup'),
  list: () => api.get<Connection[]>('/api/connections'),
  get: (id: string) => api.get<Connection>(`/api/connections/${id}`),
  create: (input: CreateConnectionInput) => api.post<Connection>('/api/connections', input),
  remove: (id: string) => api.delete<null>(`/api/connections/${id}`),
  verify: (id: string) => api.post<VerifyResult>(`/api/connections/${id}/verify`),
  cloudformation: (id: string) =>
    api.get<CloudFormationInfo>(`/api/connections/${id}/cloudformation`),
}
