import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ConnectionSetup } from '@/api/types'
import { S } from '@/lib/strings'
import { ConnectionGuide } from './ConnectionGuide'

const setup = vi.hoisted(() => ({
  data: { account_id: '111122223333', role_name: 'AutoAWSReadOnly' } as ConnectionSetup | undefined,
  isPending: false,
  isError: false,
  isFetching: false,
  refetch: vi.fn(),
}))
vi.mock('@/hooks/useConnections', () => ({ useConnectionSetup: () => setup }))
beforeEach(() => {
  setup.data = { account_id: '111122223333', role_name: 'AutoAWSReadOnly' }
  setup.isPending = false
  setup.isError = false
  setup.refetch.mockClear()
})

vi.mock('@/hooks/useTools', () => ({
  useTools: () => ({
    data: [{ aws_actions: ['ec2:DescribeInstances'] }],
    isPending: false,
    isError: false,
  }),
}))
afterEach(cleanup)

it('copies current trust policy without submitting the connection form', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const submit = vi.fn((event) => event.preventDefault())
  const view = (externalId: string) => (
    <form onSubmit={submit}>
      <ConnectionGuide externalId={externalId} />
    </form>
  )
  const { rerender } = render(view('original'))
  rerender(view('updated'))
  fireEvent.click(screen.getByRole('button', { name: `Copy: ${S.connections.guide.trustTitle}` }))
  const policy = JSON.parse(writeText.mock.calls[0][0])
  expect(policy.Statement[0].Condition.StringEquals['sts:ExternalId']).toBe('updated')
  expect(policy.Statement[0].Principal.AWS).toBe('arn:aws:iam::111122223333:root')
  expect(screen.getByText(S.connections.guide.roleIntro)).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: `Copy: ${S.connections.guide.roleNameLabel}` }),
  ).toBeInTheDocument()
  expect(
    screen.queryByText('3. AssumeRole permissions — on the AutoAWS caller'),
  ).not.toBeInTheDocument()
  expect(submit).not.toHaveBeenCalled()
  expect(await screen.findByText(S.common.copied)).toBeInTheDocument()
})

it('copies read-only permissions for the role', () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  render(<ConnectionGuide externalId="unused" />)
  fireEvent.click(screen.getByRole('button', { name: `Copy: ${S.connections.guide.readTitle}` }))
  const policy = JSON.parse(writeText.mock.calls[0][0])
  expect(policy.Statement[0].Action).toEqual([
    'ec2:DescribeInstances',
    'ec2:DescribeRegions',
    'sts:GetCallerIdentity',
  ])
  expect(policy.Statement[1].Effect).toBe('Deny')
  expect(policy.Statement[1].Action).toContain('kms:Decrypt')
})

it('does not offer an invalid trust policy when setup is unavailable', () => {
  setup.data = { account_id: null, role_name: 'AutoAWSReadOnly' }
  render(<ConnectionGuide externalId="test-external-id" />)
  expect(screen.getByRole('alert')).toHaveTextContent(S.connections.guide.setupUnavailable)
  fireEvent.click(screen.getByRole('button', { name: S.common.retry }))
  expect(setup.refetch).toHaveBeenCalledOnce()
  expect(
    screen.queryByRole('button', { name: `Copy: ${S.connections.guide.trustTitle}` }),
  ).not.toBeInTheDocument()
})

it('shows loading until the connection policy can be prepared', () => {
  setup.data = undefined
  setup.isPending = true
  render(<ConnectionGuide externalId="test-external-id" />)
  expect(screen.getByRole('status')).toHaveTextContent(S.common.loading)
  expect(
    screen.queryByRole('button', { name: `Copy: ${S.connections.guide.trustTitle}` }),
  ).not.toBeInTheDocument()
})
