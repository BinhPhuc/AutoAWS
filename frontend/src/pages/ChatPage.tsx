import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Plug } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Composer } from '@/components/chat/Composer'
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
  const [prefill, setPrefill] = useState('')
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
  const handleSend = (text: string) => {
    if (conversationId) return void send(text)
    if (!activeConnectionId) return
    create.mutate(activeConnectionId, {
      onSuccess: ({ data }) => {
        navigate(`/chat/${data.id}`, { replace: true })
        // The hook is bound to the URL param; send on next tick once it re-renders.
        pendingFirstMessage.current = text
      },
    })
  }
  const pendingFirstMessage = useRef<string | null>(null)
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
    !conversationId || (conversation.isSuccess && messages.length === 0 && !state.streaming)

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <span className="text-xs text-muted-foreground">{S.chat.connection}</span>
        <Select
          value={activeConnectionId ?? ''}
          onValueChange={(v) => {
            if (!v) return
            setActiveConnectionId(String(v))
            if (conversationId) navigate('/chat')
          }}
        >
          <SelectTrigger size="sm" className="min-w-48">
            <SelectValue>
              {connectedConnections.find((c) => c.id === activeConnectionId)?.name ??
                S.chat.selectConnection}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {connectedConnections.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name} · {c.region}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {conversation.data?.title && (
          <span className="ml-2 hidden truncate text-sm font-medium md:inline">
            {conversation.data.title}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {conversationId && conversation.isPending ? (
          <PageLoading />
        ) : conversationId && conversation.isError ? (
          <PageError error={conversation.error} onRetry={() => void conversation.refetch()} />
        ) : showEmpty && !state.pendingQuestion ? (
          <EmptyChat onPick={(text) => setPrefill(text)} />
        ) : (
          <div className="mx-auto max-w-3xl space-y-5 p-4">
            {messages.map((m) => (
              <MessageItem key={m.id} message={m} />
            ))}
            {state.pendingQuestion && (
              <>
                <UserMessage content={state.pendingQuestion} />
                <AssistantMessage
                  toolCalls={state.toolCalls}
                  answer={state.answer?.answer}
                  content={state.answer?.content}
                  streaming={state.streaming}
                  statusText={state.statusText}
                  error={state.error}
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
        streaming={state.streaming}
        disabled={create.isPending || !activeConnectionId}
        initialValue={prefill}
      />
    </div>
  )
}
