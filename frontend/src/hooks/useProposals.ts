import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { proposalsApi } from '@/api/proposals'
import type { Decision, Proposal, ProposalStatus } from '@/api/types'
import { toastApiError } from './useConnections'

export const proposalKeys = {
  all: ['proposals'] as const,
  list: (conversationId?: string) => ['proposals', 'list', conversationId ?? 'all'] as const,
  detail: (id: string) => ['proposals', id] as const,
}

/** Statuses the server is still working on: keep polling. */
export const RUNNING: ProposalStatus[] = ['APPROVED', 'EXECUTING']

const poll = (p: Proposal | undefined) => (p && RUNNING.includes(p.status) ? 2000 : false)

export function useProposal(id: string | null) {
  return useQuery({
    queryKey: proposalKeys.detail(id ?? ''),
    queryFn: async () => (await proposalsApi.get(id!)).data,
    enabled: !!id,
    refetchInterval: (q) => poll(q.state.data),
  })
}

/** Proposals of one conversation, or of every conversation with ``conversationId = 'all'``. */
export function useProposals(conversationId: string | undefined) {
  return useQuery({
    queryKey: proposalKeys.list(conversationId),
    queryFn: async () =>
      (await proposalsApi.list(conversationId === 'all' ? {} : { conversation_id: conversationId }))
        .data,
    enabled: !!conversationId,
    refetchInterval: (q) => (q.state.data?.some((p) => RUNNING.includes(p.status)) ? 2000 : false),
  })
}

export function useDecide() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      decision,
      feedback,
    }: {
      id: string
      decision: Decision
      feedback?: string
    }) => proposalsApi.decide(id, decision, feedback),
    onSuccess: ({ data, message }) => {
      toast.success(message)
      qc.setQueryData(proposalKeys.detail(data.proposal.id), data.proposal)
      void qc.invalidateQueries({ queryKey: proposalKeys.all })
    },
    onError: (e) => toastApiError(e),
  })
}

/** Proposals waiting for a decision, for the navigation badge (report §3.3: the web UI
 *  always shows pending proposals, emails may land in spam). */
export function usePendingProposals(): number {
  const { data } = useQuery({
    queryKey: [...proposalKeys.all, 'pending'],
    queryFn: async () => (await proposalsApi.list({ status: 'PENDING_APPROVAL' })).data,
    refetchInterval: 15_000,
    retry: false,
  })
  return data?.length ?? 0
}
