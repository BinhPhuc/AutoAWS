import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { conversationsApi } from '@/api/conversations'
import { toastApiError } from './useConnections'

export const conversationKeys = {
  all: ['conversations'] as const,
  lists: () => ['conversations', 'list'] as const,
  list: (connectionId?: string) => ['conversations', 'list', connectionId ?? 'all'] as const,
  detail: (id: string) => ['conversations', 'detail', id] as const,
}

export function useConversations(connectionId?: string) {
  return useQuery({
    queryKey: conversationKeys.list(connectionId),
    queryFn: async () => (await conversationsApi.list(connectionId)).data,
    enabled: connectionId !== '',
  })
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: conversationKeys.detail(id ?? ''),
    queryFn: async () => (await conversationsApi.get(id!)).data,
    enabled: !!id,
  })
}

export function useCreateConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (connectionId: string) => conversationsApi.create({ connection_id: connectionId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: conversationKeys.all }),
    onError: (e) => toastApiError(e),
  })
}

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => conversationsApi.remove(id),
    onSuccess: ({ message }) => {
      toast.success(message)
      void qc.invalidateQueries({ queryKey: conversationKeys.all })
    },
    onError: (e) => toastApiError(e),
  })
}
