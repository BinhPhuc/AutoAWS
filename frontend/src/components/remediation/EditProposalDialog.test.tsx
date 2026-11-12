import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/client'
import type { Proposal, RemediationAction } from '@/api/types'
import { S } from '@/lib/strings'
import { EditProposalDialog } from './EditProposalDialog'
import { ProposalList } from './ProposalCard'

const { api } = vi.hoisted(() => ({
  api: { get: vi.fn(), list: vi.fn(), decide: vi.fn(), actions: vi.fn(), revise: vi.fn() },
}))
vi.mock('@/api/proposals', () => ({ proposalsApi: api }))

const ACTIONS: RemediationAction[] = [
  {
    name: 'associate_route_table',
    label: 'Associate route table',
    description: '',
    aws_actions: [],
    input_schema: {
      type: 'object',
      properties: {
        subnet_id: { type: 'string', pattern: '^subnet-[0-9a-f]+$' },
        route_table_id: { type: 'string', pattern: '^rtb-[0-9a-f]+$' },
      },
      required: ['subnet_id', 'route_table_id'],
    },
  },
  {
    name: 'authorize_sg_ingress',
    label: 'Allow inbound port',
    description: '',
    aws_actions: [],
    input_schema: {
      type: 'object',
      properties: {
        group_id: { type: 'string', pattern: '^sg-[0-9a-f]+$' },
        protocol: { type: 'string', enum: ['tcp', 'udp'] },
        port: { type: 'integer', minimum: 1, maximum: 65535 },
        cidr: { type: 'string', description: 'e.g. 203.0.113.7/32' },
        description: { type: 'string', maxLength: 255 },
      },
      required: ['group_id', 'port', 'cidr'],
    },
  },
]

const base: Proposal = {
  id: 'prop_1',
  conversation_id: 'conv_1',
  message_id: 'msg_1',
  connection_id: 'conn_1',
  kind: 'fix',
  parent_id: null,
  action: 'associate_route_table',
  params: { subnet_id: 'subnet-0a1b', route_table_id: 'rtb-0c0d' },
  reason: '',
  status: 'PENDING_APPROVAL',
  preview: {
    summary: 'Associate subnet-0a1b with route table rtb-0c0d',
    changes: [],
    impact: '',
    risk: 'low',
    rollback: '',
    verify: '',
  },
  result: null,
  verification: null,
  error: null,
  history: [],
  created_at: '2026-11-13T00:00:00Z',
  updated_at: '2026-11-13T00:00:00Z',
  expires_at: null,
}

const sg: Proposal = {
  ...base,
  id: 'prop_sg',
  action: 'authorize_sg_ingress',
  params: { group_id: 'sg-0a', protocol: 'tcp', port: 22, cidr: '<your-ip>/32' },
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const t = S.remediation

/** The open dialog once the catalogue loaded and Base UI moved focus into it. */
async function openDialog(proposal: Proposal) {
  const onOpenChange = vi.fn()
  wrap(<EditProposalDialog proposal={proposal} open onOpenChange={onOpenChange} />)
  await screen.findByLabelText(Object.keys(proposal.params)[0], { exact: false })
  await waitFor(() =>
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement),
  )
  return onOpenChange
}

describe('EditProposalDialog', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    api.actions.mockResolvedValue({ data: ACTIONS, message: 'OK' })
    api.revise.mockImplementation(async (id: string, params: Record<string, unknown>) => ({
      data: { ...base, id: 'prop_2', parent_id: id, params },
      message: 'Proposal revised',
    }))
  })

  it('builds the form from the action schema and sends the edited parameters', async () => {
    const user = userEvent.setup()
    const onOpenChange = await openDialog(base)
    const rt = screen.getByLabelText('route_table_id', { exact: false })
    expect(rt).toHaveValue('rtb-0c0d')
    expect(screen.getByRole('button', { name: t.editSubmit })).toBeDisabled() // nothing changed
    await user.clear(rt)
    await user.type(rt, 'rtb-0e0f')
    await user.click(screen.getByRole('button', { name: t.editSubmit }))
    await waitFor(() =>
      expect(api.revise).toHaveBeenCalledWith('prop_1', {
        subnet_id: 'subnet-0a1b',
        route_table_id: 'rtb-0e0f',
      }),
    )
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('checks patterns, ranges and required fields before sending', async () => {
    const user = userEvent.setup()
    await openDialog(sg)
    const cidr = screen.getByLabelText('cidr', { exact: false })
    await user.clear(screen.getByLabelText('port', { exact: false }))
    await user.type(screen.getByLabelText('port', { exact: false }), '70000')
    await user.clear(screen.getByLabelText('group_id', { exact: false }))
    await user.type(screen.getByLabelText('group_id', { exact: false }), 'bad')
    await user.clear(cidr)
    await user.click(screen.getByRole('button', { name: t.editSubmit }))
    expect(screen.getByText(t.fieldInteger(1, 65535))).toBeInTheDocument()
    expect(screen.getByText(t.fieldPattern)).toBeInTheDocument()
    expect(screen.getByText(t.fieldRequired)).toBeInTheDocument()
    expect(api.revise).not.toHaveBeenCalled()
  })

  it('sends numbers as numbers and leaves empty optional fields out', async () => {
    const user = userEvent.setup()
    await openDialog(sg)
    const cidr = screen.getByLabelText('cidr', { exact: false })
    await user.clear(cidr)
    await user.type(cidr, '198.51.100.7/32')
    await user.click(screen.getByRole('button', { name: t.editSubmit }))
    await waitFor(() =>
      expect(api.revise).toHaveBeenCalledWith('prop_sg', {
        group_id: 'sg-0a',
        protocol: 'tcp',
        port: 22,
        cidr: '198.51.100.7/32',
      }),
    )
  })

  it('shows why the server refused the new parameters and stays open', async () => {
    const user = userEvent.setup()
    api.revise.mockRejectedValue(
      new ApiError({
        status_code: 422,
        message: 'Invalid request: Pre-check failed: rtb-0e0f has no active 0.0.0.0/0 route',
        error: 'VALIDATION_ERROR',
        path: '/api/proposals/prop_1/revise',
        timestamp: '',
      }),
    )
    const onOpenChange = await openDialog(base)
    const rt = screen.getByLabelText('route_table_id', { exact: false })
    await user.clear(rt)
    await user.type(rt, 'rtb-0e0f')
    await user.click(screen.getByRole('button', { name: t.editSubmit }))
    expect(await screen.findByRole('alert')).toHaveTextContent('has no active 0.0.0.0/0 route')
    expect(onOpenChange).not.toHaveBeenCalled()
  })
})

describe('Edit on a proposal card', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    api.actions.mockResolvedValue({ data: ACTIONS, message: 'OK' })
  })

  function show(p: Proposal, all: Proposal[] = [p]) {
    api.get.mockImplementation(async (id: string) => ({
      data: all.find((x) => x.id === id),
      message: 'OK',
    }))
    api.list.mockResolvedValue({ data: all, message: 'OK' })
    wrap(
      <ProposalList
        refs={[{ action: p.action, params: {}, reason: '', proposal_id: p.id, error: null }]}
      />,
    )
  }

  it.each(['PENDING_APPROVAL', 'REJECTED', 'STALE'] as const)('is offered when %s', async (s) => {
    show({ ...base, status: s })
    expect(await screen.findByRole('button', { name: t.edit })).toBeInTheDocument()
  })

  it.each(['SUCCEEDED', 'FAILED', 'EXECUTING'] as const)('is not offered when %s', async (s) => {
    show({ ...base, status: s })
    await screen.findByText(base.preview.summary)
    expect(screen.queryByRole('button', { name: t.edit })).not.toBeInTheDocument()
  })

  it('shows the revision under the original, which can no longer be edited', async () => {
    const old = { ...base, status: 'SUPERSEDED' as const }
    const revision: Proposal = {
      ...base,
      id: 'prop_2',
      parent_id: 'prop_1',
      preview: { ...base.preview, summary: 'Associate subnet-0a1b with route table rtb-0e0f' },
    }
    show(old, [old, revision])
    expect(await screen.findByText(revision.preview.summary)).toBeInTheDocument()
    expect(screen.getByText(`${t.revised}:`)).toBeInTheDocument()
    // only the revision (pending) has Edit
    expect(screen.getAllByRole('button', { name: t.edit })).toHaveLength(1)
  })
})
