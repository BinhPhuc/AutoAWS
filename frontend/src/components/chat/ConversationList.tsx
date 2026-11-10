import { NavLink, useNavigate, useParams } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
} from '@/hooks/useConversations'
import { formatRelative } from '@/lib/format'
import { S } from '@/lib/strings'
import { cn } from '@/lib/utils'

/** Conversations of the active connection (left panel of the Diagnose page). */
export function ConversationList({ connectionId }: { connectionId: string | null }) {
  const navigate = useNavigate()
  const { conversationId } = useParams()
  const conversations = useConversations(connectionId ?? '')
  const create = useCreateConversation()
  const remove = useDeleteConversation()

  const newConversation = () => {
    if (!connectionId) return navigate('/connect')
    create.mutate(connectionId, { onSuccess: ({ data }) => navigate(`/chat/${data.id}`) })
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center justify-between border-b px-3">
        <h2 className="text-sm font-semibold">{S.chat.conversations}</h2>
        <Button variant="outline" size="sm" onClick={newConversation} disabled={create.isPending}>
          <Plus />
          {S.chat.newConversation}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!connectionId ? (
          <p className="p-3 text-sm text-muted-foreground">{S.chat.noConnectedConnection}</p>
        ) : conversations.isPending ? (
          <div className="space-y-2 p-3">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : !conversations.data?.length ? (
          <p className="p-3 text-sm text-muted-foreground">{S.chat.noConversations}</p>
        ) : (
          <ul>
            {conversations.data.map((c) => {
              const active = c.id === conversationId
              return (
                <li key={c.id} className="group relative border-b">
                  <NavLink
                    to={`/chat/${c.id}`}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'block border-l-2 border-transparent py-2 pr-9 pl-3 hover:bg-muted',
                      'focus-visible:bg-muted focus-visible:outline-none',
                      active && 'border-l-primary bg-accent hover:bg-accent',
                    )}
                  >
                    <div
                      className={cn(
                        'truncate text-sm',
                        active && 'font-medium text-accent-foreground',
                      )}
                      title={c.title}
                    >
                      {c.title || S.chat.untitled}
                    </div>
                    <div className="tabular text-xs text-muted-foreground">
                      {formatRelative(c.updated_at)}
                    </div>
                  </NavLink>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={S.chat.deleteConversation}
                    className="absolute top-2.5 right-2 focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100"
                    onClick={() =>
                      remove.mutate(c.id, {
                        onSuccess: () => {
                          if (active) navigate('/chat')
                        },
                      })
                    }
                  >
                    <Trash2 />
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
