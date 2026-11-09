import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { S } from '@/lib/strings'
import { RoleSetupGuide } from './RoleSetupGuide'

const preview = vi.hoisted(() => vi.fn())
vi.mock('@/hooks/useConnections', () => ({
  useConnectionSetup: () => ({
    data: { account_id: '111122223333', role_name: 'AutoAWSReadOnly' },
    isPending: false,
  }),
  useCloudFormationPreview: (externalId: string) => {
    preview(externalId)
    return {
      data: {
        stack_name: 'AutoAWSReadOnlyRole',
        role_name: 'AutoAWSReadOnly',
        external_id: externalId,
        platform_account_id: '111122223333',
        template_yaml: `AWSTemplateFormatVersion: '2010-09-09'\nExternalId: ${externalId}`,
      },
      isPending: false,
      isError: false,
    }
  },
}))
vi.mock('@/hooks/useTools', () => ({
  useTools: () => ({
    data: [{ aws_actions: ['ec2:DescribeInstances'] }],
    isPending: false,
  }),
}))
afterEach(() => {
  cleanup()
  preview.mockClear()
})

it('offers both setup methods before saving and copies a template with the current External ID', async () => {
  const user = userEvent.setup()
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const submit = vi.fn((event) => event.preventDefault())
  const view = (externalId: string) => (
    <form onSubmit={submit}>
      <RoleSetupGuide externalId={externalId} />
    </form>
  )
  const { rerender } = render(view('autoaws-original'))
  expect(screen.getByRole('tab', { name: S.connections.form.manualSetup })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await user.click(screen.getByRole('tab', { name: S.connections.form.automaticSetup }))
  expect(
    screen.getByRole('button', { name: S.connections.cfn.downloadTemplate }),
  ).toBeInTheDocument()
  rerender(view('autoaws-updated'))
  expect(preview).toHaveBeenLastCalledWith('autoaws-updated')
  fireEvent.click(screen.getByRole('button', { name: S.connections.cfn.copyTemplate }))
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining('autoaws-updated'))
  expect(submit).not.toHaveBeenCalled()
  await user.click(screen.getByRole('tab', { name: S.connections.form.manualSetup }))
  await user.click(screen.getByRole('button', { name: S.connections.form.roleHelpButton }))
  expect(screen.getByRole('dialog', { name: S.connections.guide.roleTitle })).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: `Copy: ${S.connections.guide.connectionExternalId}` }),
  ).toBeInTheDocument()
})
