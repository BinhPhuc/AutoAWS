import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Connection } from '@/api/types'
import { S } from '@/lib/strings'
import { EditConnectionDialog } from './EditConnectionDialog'

const { api } = vi.hoisted(() => ({ api: { update: vi.fn(), verify: vi.fn() } }))
vi.mock('@/api/connections', () => ({ connectionsApi: api }))

const ROLE = 'arn:aws:iam::123456789012:role/AutoAWSReadOnly'
const base: Connection = {
  id: 'conn_1',
  name: 'Lab',
  type: 'role',
  region: 'ap-southeast-1',
  role_arn: ROLE,
  external_id: 'autoaws-0000000000000001-aaaaaaaaaaaaaaaaaaaaaaaa',
  status: 'failed',
  account_id: null,
  access_key_id_masked: null,
  remediation_role_arn: null,
  remediation_enabled: false,
  last_error: 'UnauthorizedOperation',
  last_verified_at: null,
  created_at: '2026-11-10T00:00:00Z',
}

/** Renders the open dialog and waits for its initial focus (Base UI moves focus into the
 * dialog after mounting; typing before that would lose keystrokes). */
async function renderDialog(connection: Connection = base) {
  const onOpenChange = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <EditConnectionDialog connection={connection} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  await waitFor(() => expect(screen.getByLabelText(S.connections.form.name)).toHaveFocus())
  return onOpenChange
}

const t = S.connections.edit

describe('EditConnectionDialog', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    api.update.mockImplementation(async (id: string, patch: Partial<Connection>) => ({
      data: {
        ...base,
        ...patch,
        id,
        status: 'region' in patch || 'role_arn' in patch ? 'pending' : base.status,
      },
      message: 'Connection updated',
    }))
    api.verify.mockResolvedValue({ data: { status: 'connected', error: null }, message: 'ok' })
  })

  it('sends only the changed name and does not re-verify', async () => {
    const user = userEvent.setup()
    const onOpenChange = await renderDialog({ ...base, status: 'connected', last_error: null })
    expect(screen.getByRole('button', { name: t.save })).toBeDisabled()
    const name = screen.getByLabelText(S.connections.form.name)
    await user.clear(name)
    await user.type(name, 'Lab 2')
    await user.click(screen.getByRole('button', { name: t.save }))
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('conn_1', { name: 'Lab 2' }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(api.verify).not.toHaveBeenCalled()
  })

  it('a new role ARN is saved, then verified, keeping the External ID', async () => {
    const user = userEvent.setup()
    await renderDialog()
    expect(screen.getByText(t.externalIdNote(base.external_id!))).toBeInTheDocument()
    const role = screen.getByLabelText(S.connections.form.roleArn)
    await user.clear(role)
    await user.type(role, `${ROLE}-v2`)
    expect(screen.getByText(t.reverifyNote)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: t.save }))
    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith('conn_1', { role_arn: `${ROLE}-v2` }),
    )
    await waitFor(() => expect(api.verify).toHaveBeenCalledWith('conn_1'))
  })

  it('refuses an invalid role ARN or an empty name', async () => {
    const user = userEvent.setup()
    await renderDialog()
    await user.clear(screen.getByLabelText(S.connections.form.roleArn))
    await user.type(screen.getByLabelText(S.connections.form.roleArn), 'nope')
    await user.clear(screen.getByLabelText(S.connections.form.name))
    await user.click(screen.getByRole('button', { name: t.save }))
    expect(screen.getByText(S.connections.form.errors.roleArnInvalid)).toBeInTheDocument()
    expect(screen.getByText(S.connections.form.errors.nameRequired)).toBeInTheDocument()
    expect(api.update).not.toHaveBeenCalled()
  })

  it('has no role field for access key connections', async () => {
    await renderDialog({ ...base, type: 'access_key', role_arn: null, external_id: null })
    expect(screen.queryByLabelText(S.connections.form.roleArn)).not.toBeInTheDocument()
  })
})
