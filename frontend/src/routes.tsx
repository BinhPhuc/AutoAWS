import { createBrowserRouter } from 'react-router-dom'
import { AuthGate } from '@/components/auth/AuthGate'
import { AppShell } from '@/components/layout/AppShell'
import { AuthCallbackPage } from '@/pages/AuthCallbackPage'
import { ChatPage } from '@/pages/ChatPage'
import { ChecklistPage } from '@/pages/ChecklistPage'
import { ConnectPage } from '@/pages/ConnectPage'
import { HomeRedirect } from '@/pages/HomeRedirect'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProposalsPage } from '@/pages/ProposalsPage'
import { RootErrorPage, RouteErrorPage } from '@/pages/RouteErrorPage'
import { ToolsPage } from '@/pages/ToolsPage'

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
    children: [
      {
        // Page errors render inside AppShell so navigation stays available.
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <HomeRedirect /> },
          { path: 'connect', element: <ConnectPage /> },
          { path: 'chat/:conversationId?', element: <ChatPage /> },
          { path: 'proposals', element: <ProposalsPage /> },
          { path: 'tools', element: <ToolsPage /> },
          { path: 'checklist', element: <ChecklistPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
