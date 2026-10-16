import { NavLink, useNavigate, useParams } from 'react-router-dom'
import { ClipboardCheck, MessageSquare, Moon, Plug, Plus, Sun, Trash2 } from 'lucide-react'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { S } from '@/lib/strings'
import { formatRelative } from '@/lib/format'
import { useConnections } from '@/hooks/useConnections'
import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
} from '@/hooks/useConversations'
import { useActiveConnection } from '@/hooks/useActiveConnection'
import { ConnectionBadge } from './ConnectionBadge'

const navItems = [
  { to: '/connect', label: S.nav.connect, icon: Plug },
  { to: '/chat', label: S.nav.chat, icon: MessageSquare, end: false },
  { to: '/checklist', label: S.nav.checklist, icon: ClipboardCheck },
]

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate()
  const { conversationId } = useParams()
  const { resolvedTheme, setTheme } = useTheme()
  const { data: connections } = useConnections()
  const { activeConnectionId } = useActiveConnection(connections)
  const conversations = useConversations(activeConnectionId ?? '')
  const create = useCreateConversation()
  const remove = useDeleteConversation()

  const active = connections?.find((c) => c.id === activeConnectionId)

  const newConversation = () => {
    if (!activeConnectionId) return navigate('/connect')
    create.mutate(activeConnectionId, {
      onSuccess: ({ data }) => {
        navigate(`/chat/${data.id}`)
        onNavigate?.()
      },
    })
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 items-center justify-between px-4">
        <div className="leading-tight">
          <div className="font-heading font-semibold">{S.app.name}</div>
          <div className="text-[11px] text-muted-foreground">{S.app.tagline}</div>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={S.nav.toggleTheme}
          onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
        >
          <Sun className="dark:hidden" />
          <Moon className="hidden dark:block" />
        </Button>
      </div>
      <Separator />

      <nav className="flex flex-col gap-0.5 p-2">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end ?? true}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-sidebar-accent',
                isActive && 'bg-sidebar-accent font-medium',
              )
            }
          >
            <Icon className="size-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <Separator />

      <div className="flex items-center justify-between px-4 py-2">
        <span className="text-xs font-medium text-muted-foreground uppercase">
          {S.chat.conversations}
        </span>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={S.chat.newConversation}
          onClick={newConversation}
          disabled={create.isPending}
        >
          <Plus />
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1 px-2">
        {!activeConnectionId ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">{S.chat.noConnectedConnection}</p>
        ) : conversations.isPending ? (
          <div className="space-y-2 px-2 py-2">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
        ) : !conversations.data?.length ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">{S.chat.noConversations}</p>
        ) : (
          <ul className="space-y-0.5 pb-2">
            {conversations.data.map((c) => (
              <li key={c.id} className="group relative">
                <NavLink
                  to={`/chat/${c.id}`}
                  onClick={onNavigate}
                  className={cn(
                    'block rounded-md px-2 py-1.5 pr-8 text-sm hover:bg-sidebar-accent',
                    c.id === conversationId && 'bg-sidebar-accent',
                  )}
                >
                  <div className="truncate">{c.title || S.chat.untitled}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {formatRelative(c.updated_at)}
                  </div>
                </NavLink>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={S.chat.deleteConversation}
                  className="absolute top-1.5 right-1 opacity-0 group-hover:opacity-100"
                  onClick={() =>
                    remove.mutate(c.id, {
                      onSuccess: () => {
                        if (c.id === conversationId) navigate('/chat')
                      },
                    })
                  }
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>

      <Separator />
      <div className="p-3">
        <ConnectionBadge connection={active} />
      </div>
    </div>
  )
}
