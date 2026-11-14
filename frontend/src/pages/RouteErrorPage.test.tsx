import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NotFoundPage } from './NotFoundPage'
import { RouteErrorPage } from './RouteErrorPage'

function renderAt(path: string, routes: Parameters<typeof createMemoryRouter>[0]) {
  return render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />)
}

afterEach(() => vi.restoreAllMocks())

describe('error pages', () => {
  it('shows the 404 page with the requested path and navigation links', () => {
    renderAt('/does/not/exist?x=1', [{ path: '*', element: <NotFoundPage /> }])
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByText('/does/not/exist?x=1')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Diagnose/ })).toHaveAttribute('href', '/chat')
    expect(screen.getByRole('link', { name: /Back to home/ })).toHaveAttribute('href', '/')
  })

  it('shows the crash page with details when a route throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    renderAt('/boom', [
      {
        path: '/boom',
        element: <Boom />,
        errorElement: <RouteErrorPage />,
      },
    ])
    expect(screen.getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload page' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Copy details/ })).toBeInTheDocument()
  })
})

function Boom(): React.ReactElement {
  throw new Error('kaboom')
}
