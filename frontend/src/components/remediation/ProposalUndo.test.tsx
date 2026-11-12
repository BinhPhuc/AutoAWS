import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Proposal } from '@/api/types'
import { S } from '@/lib/strings'
import { ProposalList } from './ProposalCard'

const { api } = vi.hoisted(() => ({
  api: { get: vi.fn(), list: vi.fn(), decide: vi.fn(), actions: vi.fn(), rollback: vi.fn() },
}))
vi.mock('@/api/proposals', () => ({ proposalsApi: api }))

const applied: Proposal = {
  id: 'prop_1',
  conversation_id: 'conv_1',
  message_id: 'msg_1',
  connection_id: 'conn_1',
  kind: 'fix',
  parent_id: null,
  action: 'associate_route_table',
  params: { subnet_id: 'subnet-0a1b', route_table_id: 'rtb-0c0d' },
  reason: '',
  status: 'SUCCEEDED',
  preview: {
    summary: 'Associate subnet-0a1b with route table rtb-0c0d',
    changes: [],
    impact: '',
    risk: 'low',
    rollback: 'Associate subnet-0a1b back with rtb-07c9',
    verify: '',
  },
  result: {},
  verification: { ok: true, details: 'ok' },
  error: null,
  history: [],
  created_at: '2026-11-13T00:00:00Z',
  updated_at: '2026-11-13T00:00:00Z',
  expires_at: null,
}

const rollback = (status: Proposal['status']): Proposal => ({
  ...applied,
  id: 'prop_rb',
  kind: 'rollback',
  parent_id: 'prop_1',
  status,
  preview: { ...applied.preview, summary: 'Undo prop_1: associate subnet-0a1b back' },
})

const t = S.remediation

function show(all: Proposal[], id = 'prop_1') {
  api.get.mockImplementation(async (x: string) => ({
    data: all.find((p) => p.id === x),
    message: 'OK',
  }))
  api.list.mockResolvedValue({ data: all, message: 'OK' })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ProposalList
        refs={[{ action: applied.action, params: {}, reason: '', proposal_id: id, error: null }]}
      />
    </QueryClientProvider>,
  )
}

describe('Undo change', () => {
  afterEach(cleanup)
  beforeEach(() => vi.clearAllMocks())

  it('proposes a rollback for an applied fix', async () => {
    const user = userEvent.setup()
    api.rollback.mockResolvedValue({
      data: rollback('PENDING_APPROVAL'),
      message: 'Rollback proposed',
    })
    show([applied])
    await user.click(await screen.findByRole('button', { name: t.requestRollback }))
    await waitFor(() => expect(api.rollback).toHaveBeenCalledWith('prop_1'))
  })

  it('is hidden while a rollback waits, and the rollback can be approved', async () => {
    show([rollback('PENDING_APPROVAL'), applied])
    expect(await screen.findByText(/Undo prop_1/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t.requestRollback })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: t.approve })).toBeInTheDocument()
  })

  it('comes back after the rollback was rejected', async () => {
    show([rollback('REJECTED'), applied])
    expect(await screen.findByRole('button', { name: t.requestRollback })).toBeInTheDocument()
  })

  it.each(['PENDING_APPROVAL', 'FAILED', 'ROLLED_BACK'] as const)(
    'is not offered for a %s fix',
    async (status) => {
      show([{ ...applied, status }])
      await screen.findByText(applied.preview.summary)
      expect(screen.queryByRole('button', { name: t.requestRollback })).not.toBeInTheDocument()
    },
  )

  it('is not offered on a rollback itself', async () => {
    show([rollback('SUCCEEDED'), applied], 'prop_rb')
    await screen.findByText(/Undo prop_1/)
    expect(screen.queryByRole('button', { name: t.requestRollback })).not.toBeInTheDocument()
  })
})
