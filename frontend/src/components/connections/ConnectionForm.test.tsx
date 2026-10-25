import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { S } from '@/lib/strings'
import { ConnectionForm } from './ConnectionForm'

const mocks = vi.hoisted(() => ({ create: vi.fn(), verify: vi.fn() }))
vi.mock('@/hooks/useConnections', () => ({
  useCreateConnection: () => ({ mutate: mocks.create, isPending: false }),
  useVerifyConnection: () => ({ mutate: mocks.verify, isPending: false }),
  useCloudFormationPreview: (externalId: string) => ({
    data: {
      stack_name: 'AutoAWSReadOnlyRole',
      role_name: 'AutoAWSReadOnly',
      external_id: externalId,
      platform_account_id: '111122223333',
      template_yaml: 'Resources: {}',
    },
    isPending: false,
  }),
}))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('verifies a saved role immediately and retries without creating another connection', async () => {
  const user = userEvent.setup()
  const onCreated = vi.fn()
  const record = {
    id: 'conn-test',
    type: 'role',
    role_arn: 'arn:aws:iam::123456789012:role/AutoAWSReadOnly',
  }
  mocks.create.mockImplementation((_input, options) => options.onSuccess({ data: record }))
  mocks.verify.mockImplementationOnce((_id, options) =>
    options.onSuccess({ data: { status: 'failed' } }),
  )
  mocks.verify.mockImplementationOnce((_id, options) =>
    options.onSuccess({ data: { status: 'connected' } }),
  )
  render(<ConnectionForm onCreated={onCreated} />)
  expect(screen.queryByRole('tab', { name: 'Access Key' })).not.toBeInTheDocument()
  expect(screen.getByRole('tab', { name: S.connections.form.manualSetup })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: S.connections.form.automaticSetup })).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: S.connections.form.roleHelpButton }),
  ).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: S.connections.cfn.downloadTemplate }),
  ).not.toBeInTheDocument()
  const externalId = screen.getByLabelText(S.connections.form.externalId).getAttribute('value')
  await user.click(screen.getByRole('tab', { name: S.connections.form.automaticSetup }))
  expect(screen.getByLabelText(S.connections.form.externalId)).toHaveValue(externalId)
  expect(
    screen.getByRole('button', { name: S.connections.cfn.downloadTemplate }),
  ).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: S.connections.form.roleHelpButton }),
  ).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Access key ID')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Secret access key')).not.toBeInTheDocument()
  await user.type(screen.getByLabelText(S.connections.form.name, { exact: true }), 'My account')
  await user.type(
    screen.getByLabelText(S.connections.form.roleArn, { exact: true }),
    record.role_arn,
  )
  await user.click(screen.getByRole('button', { name: S.connections.form.submitRole }))
  expect(mocks.create).toHaveBeenCalledOnce()
  expect(mocks.create.mock.calls[0][0]).toMatchObject({ type: 'role', role_arn: record.role_arn })
  expect(mocks.verify).toHaveBeenCalledWith('conn-test', expect.any(Object))
  expect(onCreated).not.toHaveBeenCalled()
  expect(screen.queryByText(S.connections.cfn.title)).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: S.connections.verify }))
  expect(mocks.create).toHaveBeenCalledOnce()
  expect(mocks.verify).toHaveBeenCalledTimes(2)
  expect(onCreated).toHaveBeenCalledWith(record)
})
