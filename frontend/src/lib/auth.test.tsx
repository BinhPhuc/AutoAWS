import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AuthProvider } from './auth'
import { S } from './strings'

const mocks = vi.hoisted(() => ({ initialize: vi.fn(), signIn: vi.fn(), ended: () => {} }))
vi.mock('@/api/auth', () => ({
  initializeAuth: mocks.initialize,
  signIn: mocks.signIn,
  signOut: vi.fn(),
  onSessionEnded: (callback: () => void) => {
    mocks.ended = callback
    return () => {}
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})
afterEach(cleanup)

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <p>Private workspace</p>
      </AuthProvider>
    </QueryClientProvider>,
  )
  return client
}

it('gates the workspace until authenticated and opens Cognito sign-in', async () => {
  mocks.initialize.mockResolvedValue(null)
  mocks.signIn.mockResolvedValue(undefined)
  setup()
  const button = await screen.findByRole('button', { name: S.auth.signIn })
  expect(screen.queryByText('Private workspace')).not.toBeInTheDocument()
  fireEvent.click(button)
  expect(mocks.signIn).toHaveBeenCalledOnce()
})

it('unmounts private content and clears cached data when the session ends', async () => {
  mocks.initialize.mockResolvedValue({ user_id: 'alice', username: 'Alice' })
  const client = setup()
  await screen.findByText('Private workspace')
  client.setQueryData(['connections'], [{ name: 'Private account' }])
  localStorage.setItem('autoaws.activeConnectionId', 'private-id')
  act(() => mocks.ended())
  expect(screen.queryByText('Private workspace')).not.toBeInTheDocument()
  expect(client.getQueryData(['connections'])).toBeUndefined()
  expect(localStorage.getItem('autoaws.activeConnectionId')).toBeNull()
  expect(screen.getByRole('button', { name: S.auth.signIn })).toBeInTheDocument()
})
