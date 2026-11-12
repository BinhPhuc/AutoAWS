import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { connectionsApi } from '@/api/connections'
import { ApiError } from '@/api/client'
import type { ConnectionPatch, CreateConnectionInput } from '@/api/types'

export const connectionKeys = {
  all: ['connections'] as const,
  detail: (id: string) => ['connections', id] as const,
  cfn: (id: string) => ['connections', id, 'cloudformation'] as const,
}

export function useConnections() {
  return useQuery({
    queryKey: connectionKeys.all,
    queryFn: async () => (await connectionsApi.list()).data,
  })
}

export const connectionSetupKey = ['connection-setup'] as const

/** Setup info + a server-issued External ID. Fetched once and kept: the ID must not change
 * while the user creates the role with it (refetch only on "Regenerate" or after saving). */
export function useConnectionSetup() {
  return useQuery({
    queryKey: connectionSetupKey,
    queryFn: async () => (await connectionsApi.setup()).data,
    staleTime: Infinity,
    gcTime: Infinity,
  })
}

export function useCloudFormationPreview(externalId: string) {
  return useQuery({
    queryKey: ['cloudformation-preview', externalId],
    queryFn: async () => (await connectionsApi.cloudformationPreview(externalId)).data,
    enabled: /^[A-Za-z0-9_+=,.@:/-]{2,1224}$/.test(externalId),
  })
}

export function useCloudFormation(id: string | null) {
  return useQuery({
    queryKey: connectionKeys.cfn(id ?? ''),
    queryFn: async () => (await connectionsApi.cloudformation(id!)).data,
    enabled: !!id,
  })
}

export function toastApiError(err: unknown, fallback = 'Something went wrong') {
  toast.error(err instanceof ApiError ? err.message : fallback)
}

export function useCreateConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateConnectionInput) => connectionsApi.create(input),
    onSuccess: ({ message }) => {
      toast.success(message)
      void qc.invalidateQueries({ queryKey: connectionKeys.all })
    },
    onError: (e) => toastApiError(e),
  })
}

export function useVerifyConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => connectionsApi.verify(id),
    onSuccess: ({ data, message }) => {
      if (data.status === 'connected') toast.success(message)
      else toast.error(message, { description: data.error ?? undefined })
      void qc.invalidateQueries({ queryKey: connectionKeys.all })
    },
    onError: (e) => toastApiError(e),
  })
}

export function useDeleteConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => connectionsApi.remove(id),
    onSuccess: ({ message }) => {
      toast.success(message)
      void qc.invalidateQueries({ queryKey: connectionKeys.all })
      void qc.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: (e) => toastApiError(e),
  })
}

export function useSetRemediationRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, arn }: { id: string; arn: string | null }) =>
      connectionsApi.setRemediationRole(id, arn),
    onSuccess: ({ message }) => {
      toast.success(message)
      void qc.invalidateQueries({ queryKey: connectionKeys.all })
    },
    onError: (e) => toastApiError(e),
  })
}

/** Edit name / region / role ARN. A changed region or role comes back `pending`: verify it
 * right away, like a new connection. */
export function useUpdateConnection() {
  const qc = useQueryClient()
  const verify = useVerifyConnection()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: ConnectionPatch }) =>
      connectionsApi.update(id, patch),
    onSuccess: ({ data, message }) => {
      toast.success(message)
      void qc.invalidateQueries({ queryKey: connectionKeys.all })
      if (data.status === 'pending') verify.mutate(data.id)
    },
    onError: (e) => toastApiError(e),
  })
}
