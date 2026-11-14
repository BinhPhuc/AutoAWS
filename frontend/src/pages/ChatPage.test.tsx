import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEffect } from 'react'
import type { Connection } from '@/api/types'
import { useActiveConnection } from '@/hooks/useActiveConnection'
import { ChatPage } from './ChatPage'

const state = vi.hoisted(() => ({
  conversationId: 'conversation-a' as string | undefined,
  connectionId: 'lab-a',
  loaded: true,
}))
const connections = [
  { id: 'lab-a', status: 'connected' },
  { id: 'lab-b', status: 'connected' },
] as Connection[]

vi.mock('react-router-dom', () => ({
  useParams: () => ({ conversationId: state.conversationId }),
  useNavigate: () => vi.fn(),
  Link: () => null,
}))
vi.mock('@/hooks/useConnections', () => ({
  useConnections: () => ({ data: connections }),
}))
vi.mock('@/hooks/useConversations', () => ({
  useConversation: () => ({
    data: state.loaded ? { connection_id: state.connectionId, messages: [] } : undefined,
    isSuccess: state.loaded,
  }),
  useCreateConversation: () => ({}),
}))
vi.mock('@/hooks/useSendMessage', () => ({
  useSendMessage: () => ({ state: { toolCalls: [] }, send: vi.fn(), stop: vi.fn() }),
}))
vi.mock('@/components/chat/ConversationList', () => ({ ConversationList: () => null }))
vi.mock('@/components/chat/Composer', () => ({ Composer: () => null }))
vi.mock('@/components/chat/EmptyChat', () => ({ EmptyChat: () => null }))

let selection: ReturnType<typeof useActiveConnection>
function Page() {
  const active = useActiveConnection(connections)
  useEffect(() => {
    selection = active
  }, [active])
  return <ChatPage />
}

afterEach(cleanup)

describe('conversation connection selection', () => {
  it('keeps the first lab switch while navigation away from a conversation is pending', () => {
    state.conversationId = 'conversation-a'
    state.connectionId = 'lab-a'
    state.loaded = true
    const page = render(<Page />)
    expect(selection.activeConnectionId).toBe('lab-a')

    // The shared selection updates before the router finishes leaving the old chat.
    act(() => selection.setActiveConnectionId('lab-b'))
    expect(selection.activeConnectionId).toBe('lab-b')
    state.conversationId = undefined
    page.rerender(<Page />)
    expect(selection.activeConnectionId).toBe('lab-b')

    // Explicitly reopening that conversation must still select its original lab.
    state.conversationId = 'conversation-a'
    page.rerender(<Page />)
    expect(selection.activeConnectionId).toBe('lab-a')
  })

  it('waits for conversation data and selects the lab when opening another conversation', () => {
    state.conversationId = 'conversation-a'
    state.connectionId = 'lab-a'
    state.loaded = true
    const page = render(<Page />)
    state.conversationId = 'conversation-b'
    state.connectionId = 'lab-b'
    state.loaded = false
    page.rerender(<Page />)
    expect(selection.activeConnectionId).toBe('lab-a')
    state.loaded = true
    page.rerender(<Page />)
    expect(selection.activeConnectionId).toBe('lab-b')
  })
})
