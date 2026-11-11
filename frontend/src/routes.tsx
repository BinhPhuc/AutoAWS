import { createBrowserRouter } from 'react-router-dom'
import { AuthGate } from '@/components/auth/AuthGate'
import { AppShell } from '@/components/layout/AppShell'
import { PageLoading } from '@/components/layout/PageState'
import { AuthCallbackPage } from '@/pages/AuthCallbackPage'
import { ChecklistPage } from '@/pages/ChecklistPage'
import { HomeRedirect } from '@/pages/HomeRedirect'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { RootErrorPage, RouteErrorPage } from '@/pages/RouteErrorPage'

export const router = createBrowserRouter([
  { path: '/auth/callback', element: <AuthCallbackPage />, errorElement: <RootErrorPage /> },
  {
    path: '/',
    element: (
      <AuthGate>
        <AppShell />
      </AuthGate>
    ),
    errorElement: <RootErrorPage />,
    HydrateFallback: PageLoading,
    children: [
      {
        // Page errors render inside AppShell so navigation stays available.
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <HomeRedirect /> },
          {
            path: 'connect',
            lazy: async () => ({ Component: (await import('@/pages/ConnectPage')).ConnectPage }),
          },
          {
            path: 'chat/:conversationId?',
            lazy: async () => ({ Component: (await import('@/pages/ChatPage')).ChatPage }),
          },
          {
            path: 'proposals',
            lazy: async () => ({
              Component: (await import('@/pages/ProposalsPage')).ProposalsPage,
            }),
          },
          {
            path: 'tools',
            lazy: async () => ({ Component: (await import('@/pages/ToolsPage')).ToolsPage }),
          },
          { path: 'checklist', element: <ChecklistPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
