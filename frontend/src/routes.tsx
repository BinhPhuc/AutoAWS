import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { ChatPage } from '@/pages/ChatPage'
import { ChecklistPage } from '@/pages/ChecklistPage'
import { ConnectPage } from '@/pages/ConnectPage'
import { HomeRedirect } from '@/pages/HomeRedirect'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { RootErrorPage, RouteErrorPage } from '@/pages/RouteErrorPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    // Last resort: AppShell itself crashed, so there is no sidebar to keep.
    errorElement: <RootErrorPage />,
    children: [
      {
        // Pathless layout route: errors thrown by a page render inside AppShell.
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <HomeRedirect /> },
          { path: 'connect', element: <ConnectPage /> },
          { path: 'chat/:conversationId?', element: <ChatPage /> },
          { path: 'checklist', element: <ChecklistPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
