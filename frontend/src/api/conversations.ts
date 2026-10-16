import { api } from './client'
import type { Conversation, CreateConversationInput } from './types'

export const conversationsApi = {
  list: (connectionId?: string) =>
    api.get<Conversation[]>(
      connectionId
        ? `/api/conversations?connection_id=${encodeURIComponent(connectionId)}`
        : '/api/conversations',
    ),
  get: (id: string) => api.get<Conversation>(`/api/conversations/${id}`),
  create: (input: CreateConversationInput) => api.post<Conversation>('/api/conversations', input),
  remove: (id: string) => api.delete<null>(`/api/conversations/${id}`),
  messagesPath: (id: string) => `/api/conversations/${id}/messages`,
}
