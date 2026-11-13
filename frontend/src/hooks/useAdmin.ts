import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { adminApi } from '@/api/admin'
import type { LlmConfigInput } from '@/api/types'
import { toastApiError } from './useConnections'

const llmKey = ['admin', 'llm'] as const

export function useLlmConfig(enabled = true) {
  return useQuery({
    queryKey: llmKey,
    queryFn: async () => (await adminApi.getLlm()).data,
    enabled,
  })
}

export function useSaveLlmConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: LlmConfigInput) => adminApi.saveLlm(input),
    onSuccess: ({ data, message }) => {
      toast.success(message)
      qc.setQueryData(llmKey, data)
    },
  })
}

export function useResetLlmConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => adminApi.resetLlm(),
    onSuccess: ({ data, message }) => {
      toast.success(message)
      qc.setQueryData(llmKey, data)
    },
    onError: (e) => toastApiError(e),
  })
}

export function useTestLlm() {
  return useMutation({
    mutationFn: async () => (await adminApi.testLlm()).data,
    onError: (e) => toastApiError(e),
  })
}
