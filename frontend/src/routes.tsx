import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { ChatPage } from '@/pages/ChatPage'
import { ChecklistPage } from '@/pages/ChecklistPage'
import { ConnectPage } from '@/pages/ConnectPage'
import { HomeRedirect } from '@/pages/HomeRedirect'
import { ProposalsPage } from '@/pages/ProposalsPage'
import { ToolsPage } from '@/pages/ToolsPage'

export const router = createBrowserRouter([
  { path: '/auth/callback', element: <Navigate to="/" replace /> },
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <HomeRedirect /> },
      { path: 'connect', element: <ConnectPage /> },
      { path: 'chat/:conversationId?', element: <ChatPage /> },
      { path: 'proposals', element: <ProposalsPage /> },
      { path: 'tools', element: <ToolsPage /> },
      { path: 'checklist', element: <ChecklistPage /> },
    ],
  },
])
