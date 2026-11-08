import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ListTree, Plug } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Composer } from '@/components/chat/Composer'
import { ConversationList } from '@/components/chat/ConversationList'
import { EmptyChat } from '@/components/chat/EmptyChat'
import { AssistantMessage, MessageItem, UserMessage } from '@/components/chat/Messages'
import { EmptyState, PageError, PageLoading } from '@/components/layout/PageState'
import { useActiveConnection } from '@/hooks/useActiveConnection'
import { useConnections } from '@/hooks/useConnections'
import { useConversation, useCreateConversation } from '@/hooks/useConversations'
import { useSendMessage } from '@/hooks/useSendMessage'
import { S } from '@/lib/strings'

export function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const connections = useConnections()
  const { activeConnectionId, setActiveConnectionId, connectedConnections } = useActiveConnection(
    connections.data,
  )
  const conversation = useConversation(conversationId)
  const create = useCreateConversation()
  const { state, send, stop } = useSendMessage(conversationId)
  // A live turn is shown only in the conversation it belongs to; while another conversation
  // is streaming, this one can be read but not sent to.
  const live = state.conversationId === conversationId ? state : null
  const busyElsewhere = state.streaming && !live
  const [prefill, setPrefill] = useState('')
  const [listOpen, setListOpen] = useState(false)
  // Close the mobile drawer once a conversation is opened.
  const [listFor, setListFor] = useState(conversationId)
  if (listFor !== conversationId) {
    setListFor(conversationId)
    setListOpen(false)
  }
  const bottomRef = useRef<HTMLDivElement>(null)

  // Keep the active connection in sync with the opened conversation.
  useEffect(() => {
    const cid = conversation.data?.connection_id
    if (cid && cid !== activeConnectionId && connectedConnections.some((c) => c.id === cid)) {
      setActiveConnectionId(cid)
    }
  }, [
    conversation.data?.connection_id,
    activeConnectionId,
    connectedConnections,
    setActiveConnectionId,
  ])

  // Auto-scroll on new content.
  const messageCount = conversation.data?.messages?.length ?? 0
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messageCount, state.toolCalls.length, state.answer, state.statusText])

  /** Sends the first message: creates a conversation on demand, then streams. */
  const pendingFirstMessage = useRef<string | null>(null)
  const handleSend = (text: string) => {
    if (conversationId) return void send(text)
    if (!activeConnectionId) return
    create.mutate(activeConnectionId, {
      onSuccess: ({ data }) => {
        // The hook is bound to the URL param; send once the page re-renders with the new id.
        pendingFirstMessage.current = text
        navigate(`/chat/${data.id}`, { replace: true })
      },
    })
  }
  useEffect(() => {
    if (conversationId && pendingFirstMessage.current) {
      const text = pendingFirstMessage.current
      pendingFirstMessage.current = null
      void send(text)
    }
  }, [conversationId, send])

  if (connections.isPending) return <PageLoading />
  if (connections.isError)
    return <PageError error={connections.error} onRetry={() => void connections.refetch()} />

  if (connectedConnections.length === 0) {
    return (
      <EmptyState
        icon={<Plug className="size-8" />}
        title={S.chat.noConnectedConnection}
        action={<Button render={<Link to="/connect" />}>{S.chat.goToConnections}</Button>}
      />
    )
  }

  const messages = conversation.data?.messages ?? []
  const showEmpty =
    !conversationId || (conversation.isSuccess && messages.length === 0 && !live?.streaming)
  // The server stores the question when the turn starts, so a refetch during the turn (e.g.
  // after switching away and back) already ends with it: render the question only once.
  const lastMessage = messages.at(-1)
  const questionStored =
    lastMessage?.role === 'user' && lastMessage.content === live?.pendingQuestion

  return (
    <div className="flex h-full">
      <aside className="hidden w-72 shrink-0 border-r bg-card lg:block">
        <ConversationList connectionId={activeConnectionId} />
      </aside>

      <Sheet open={listOpen} onOpenChange={setListOpen}>
        <SheetContent side="left" className="w-80 p-0" showCloseButton>
          <SheetTitle className="sr-only">{S.chat.conversations}</SheetTitle>
          <ConversationList connectionId={activeConnectionId} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-10 shrink-0 items-center border-b bg-card px-3 lg:hidden">
          <Button variant="ghost" size="sm" onClick={() => setListOpen(true)}>
            <ListTree />
            {S.chat.conversations}
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {conversationId && conversation.isPending ? (
            <PageLoading />
          ) : conversationId && conversation.isError ? (
            <PageError error={conversation.error} onRetry={() => void conversation.refetch()} />
          ) : showEmpty && !live?.pendingQuestion ? (
            <EmptyChat onPick={(text) => setPrefill(text)} />
          ) : (
            <div className="mx-auto w-full max-w-5xl space-y-4 p-4 md:p-6">
              {messages.map((m) => (
                <MessageItem key={m.id} message={m} />
              ))}
              {live?.pendingQuestion && (
                <>
                  {!questionStored && <UserMessage content={live.pendingQuestion} />}
                  <AssistantMessage
                    toolCalls={live.toolCalls}
                    answer={live.answer?.answer}
                    content={live.answer?.content}
                    streaming={live.streaming}
                    statusText={live.statusText}
                    error={live.error}
                  />
                </>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <Composer
          onSend={handleSend}
          onStop={stop}
          streaming={!!live?.streaming}
          disabled={create.isPending || !activeConnectionId || busyElsewhere}
          initialValue={prefill}
        />
      </div>
    </div>
  )
}
