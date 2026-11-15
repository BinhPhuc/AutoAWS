import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Proposal } from '@/api/types'
import { ProposalList } from './ProposalCard'

const { api } = vi.hoisted(() => ({
  api: { get: vi.fn(), list: vi.fn(), decide: vi.fn(), actions: vi.fn() },
}))
vi.mock('@/api/proposals', () => ({ proposalsApi: api }))

const pending: Proposal = {
  id: 'prop_1',
  conversation_id: 'conv_1',
  message_id: 'msg_1',
  connection_id: 'conn_1',
  kind: 'fix',
  parent_id: null,
  action: 'route_table_associate',
  params: { subnet_id: 'subnet-0a1b', route_table_id: 'rtb-public' },
  reason: 'Gắn subnet về route table public',
  status: 'PENDING_APPROVAL',
  preview: {
    summary: 'Associate subnet-0a1b with route table rtb-public',
    changes: [{ field: 'Route table of subnet-0a1b', before: 'rtb-07c9', after: 'rtb-public' }],
    impact: 'Every instance in subnet-0a1b uses the new routes.',
    risk: 'low',
    rollback: 'Associate subnet-0a1b back with rtb-07c9',
    verify: 'The subnet has 0.0.0.0/0 to an Internet gateway.',
  },
  result: null,
  verification: null,
  error: null,
  history: [{ status: 'PENDING_APPROVAL', at: '2026-11-08T10:00:00Z', note: 'proposed' }],
  created_at: '2026-11-08T10:00:00Z',
  updated_at: '2026-11-08T10:00:00Z',
  expires_at: '2026-11-09T10:00:00Z',
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('ProposalList', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.list.mockReset()
    api.decide.mockReset()
    api.get.mockResolvedValue({ data: pending, message: 'OK' })
    api.list.mockResolvedValue({ data: [pending], message: 'OK' })
  })

  it('shows the preview, the refusal reason and the three decisions', async () => {
    render(
      wrap(
        <ProposalList
          refs={[
            {
              action: 'route_table_associate',
              params: {},
              reason: '',
              proposal_id: 'prop_1',
              error: null,
            },
            {
              action: 'sg_add_rule',
              params: {},
              reason: '',
              proposal_id: null,
              error: 'Pre-check failed: Port 22 is never opened to the whole Internet',
            },
          ]}
        />,
      ),
    )
    expect(
      await screen.findByText('Associate subnet-0a1b with route table rtb-public'),
    ).toBeInTheDocument()
    expect(screen.getByText('Waiting for approval')).toBeInTheDocument()
    expect(screen.getByText('rtb-07c9')).toBeInTheDocument()
    expect(screen.getByText('Low risk')).toBeInTheDocument()
    expect(screen.getByText(/never opened to the whole Internet/)).toBeInTheDocument()
    expect(screen.getByText('Not proposed')).toBeInTheDocument()

    api.decide.mockResolvedValue({
      data: { proposal: { ...pending, status: 'APPROVED' }, followup_question: null },
      message: 'Proposal approved',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith('prop_1', 'approve', ''))
  })

  it('sends feedback and hands the follow-up question to the chat', async () => {
    const onFollowup = vi.fn()
    render(
      wrap(
        <ProposalList
          refs={[
            {
              action: 'route_table_associate',
              params: {},
              reason: '',
              proposal_id: 'prop_1',
              error: null,
            },
          ]}
          onFollowup={onFollowup}
        />,
      ),
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Feedback' }))
    fireEvent.change(screen.getByLabelText('Feedback'), { target: { value: 'chỉ sửa lúc 22h' } })
    api.decide.mockResolvedValue({
      data: {
        proposal: { ...pending, status: 'SUPERSEDED' },
        followup_question: 'Góp ý: chỉ sửa lúc 22h',
      },
      message: 'Feedback sent',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send feedback' }))
    await waitFor(() =>
      expect(api.decide).toHaveBeenCalledWith('prop_1', 'feedback', 'chỉ sửa lúc 22h'),
    )
    await waitFor(() => expect(onFollowup).toHaveBeenCalledWith('Góp ý: chỉ sửa lúc 22h'))
  })
})
