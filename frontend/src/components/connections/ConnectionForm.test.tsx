import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Connection } from '@/api/types'
import { S } from '@/lib/strings'
import { ConnectionForm } from './ConnectionForm'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'

const { api } = vi.hoisted(() => ({
  api: { create: vi.fn(), verify: vi.fn(), setup: vi.fn(), cloudformationPreview: vi.fn() },
}))
vi.mock('@/api/connections', () => ({ connectionsApi: api }))
vi.mock('@/hooks/useTools', () => ({
  useTools: () => ({ data: [{ aws_actions: ['ec2:DescribeInstances'] }] }),
}))

const roleArn = 'arn:aws:iam::123456789012:role/AutoAWSReadOnly'
const conn: Connection = {
  id: 'conn_setup',
  name: 'Lab',
  type: 'role',
  region: 'ap-southeast-1',
  role_arn: roleArn,
  external_id: 'autoaws-existing',
  status: 'pending',
  account_id: null,
  access_key_id_masked: null,
  remediation_role_arn: null,
  remediation_enabled: false,
  last_error: null,
  last_verified_at: null,
  created_at: '2026-11-10T00:00:00Z',
}

function renderForm(onCreated = vi.fn(), inDialog = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const form = <ConnectionForm onCreated={onCreated} />
  render(
    <QueryClientProvider client={client}>
      {inDialog ? (
        <Dialog defaultOpen>
          <DialogContent>
            <DialogTitle>{S.connections.form.title}</DialogTitle>
            <DialogDescription>{S.connections.form.description}</DialogDescription>
            {form}
          </DialogContent>
        </Dialog>
      ) : (
        form
      )}
    </QueryClientProvider>,
  )
  return onCreated
}

describe('ConnectionForm role onboarding from dev', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    api.setup.mockResolvedValue({
      data: {
        account_id: '111122223333',
        role_name: 'AutoAWSReadOnly',
        trust_principals: ['arn:aws:iam::111122223333:role/autoaws-agent-worker'],
      },
    })
    api.cloudformationPreview.mockImplementation(async (externalId: string) => ({
      data: {
        stack_name: 'AutoAWSReadOnlyRole',
        role_name: 'AutoAWSReadOnly',
        external_id: externalId,
        platform_account_id: '111122223333',
        template_yaml: `ExternalId: ${externalId}`,
      },
    }))
    api.create.mockImplementation(async (input: { external_id: string }) => ({
      data: { ...conn, external_id: input.external_id },
    }))
    api.verify.mockResolvedValue({ data: { status: 'connected', error: null } })
  })

  it('dismisses the role guide on outside click without closing or clearing Connect', async () => {
    const user = userEvent.setup()
    renderForm(vi.fn(), true)
    await user.type(screen.getByLabelText('Name'), 'Keep this form')
    const externalId = (screen.getByLabelText('External ID') as HTMLInputElement).value
    await user.click(screen.getByRole('tab', { name: S.connections.form.manualSetup }))
    await user.click(screen.getByRole('button', { name: S.connections.form.roleHelpButton }))
    expect(screen.getByRole('dialog', { name: S.connections.guide.roleTitle })).toBeInTheDocument()
    const overlays = document.querySelectorAll('[data-slot="dialog-overlay"]')
    await user.click(overlays[overlays.length - 1])
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: S.connections.guide.roleTitle }),
      ).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('dialog', { name: S.connections.form.title })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Keep this form')
    expect(screen.getByLabelText('External ID')).toHaveValue(externalId)
  })

  it('uses the displayed External ID in the manual trust policy and create request', async () => {
    const done = renderForm()
    const externalId = (screen.getByLabelText('External ID') as HTMLInputElement).value
    expect(externalId).toMatch(/^autoaws-[a-f0-9]{24}$/)
    fireEvent.click(screen.getByRole('tab', { name: S.connections.form.manualSetup }))
    fireEvent.click(screen.getByRole('button', { name: S.connections.form.roleHelpButton }))
    const trust = await screen.findByLabelText(S.connections.guide.trustTitle)
    await waitFor(() => expect(trust.textContent).toContain(externalId))
    expect(trust.textContent).toContain('role/autoaws-agent-worker')
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Lab' } })
    fireEvent.change(screen.getByLabelText('Role ARN'), { target: { value: roleArn } })
    fireEvent.click(screen.getByRole('button', { name: 'Save & verify' }))
    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith({
        type: 'role',
        name: 'Lab',
        region: 'ap-southeast-1',
        role_arn: roleArn,
        external_id: externalId,
      }),
    )
    await waitFor(() => expect(done).toHaveBeenCalledOnce())
    expect(api.verify).toHaveBeenCalledWith('conn_setup')
  })

  it('previews CloudFormation with the current External ID before saving', async () => {
    renderForm()
    expect(screen.getAllByRole('tab')).toHaveLength(2)
    expect(screen.queryByText('Access Key')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Access key ID')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Secret access key')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /CloudFormation.*Recommended/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    fireEvent.change(screen.getByLabelText('External ID'), {
      target: { value: 'autoaws-role-policy-id' },
    })
    await screen.findByRole('button', { name: 'Download template' })
    expect(api.cloudformationPreview).toHaveBeenCalledWith('autoaws-role-policy-id')
    expect(api.create).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    const newId = (screen.getByLabelText('External ID') as HTMLInputElement).value
    expect(newId).not.toBe('autoaws-role-policy-id')
    await waitFor(() => expect(api.cloudformationPreview).toHaveBeenCalledWith(newId))
  })

  it('shows a failed verification and retries the saved connection', async () => {
    api.verify.mockResolvedValueOnce({
      data: { status: 'failed', error: 'External ID does not match trust policy' },
    })
    const done = renderForm()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Lab' } })
    fireEvent.change(screen.getByLabelText('Role ARN'), { target: { value: roleArn } })
    fireEvent.click(screen.getByRole('button', { name: 'Save & verify' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'External ID does not match trust policy',
    )
    expect(done).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /^Verify$/ }))
    await waitFor(() => expect(done).toHaveBeenCalledOnce())
    expect(api.create).toHaveBeenCalledOnce()
    expect(api.verify.mock.calls).toEqual([['conn_setup'], ['conn_setup']])
  })
})
