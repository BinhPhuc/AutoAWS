import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ChevronRight, Menu, Moon, Sun } from 'lucide-react'
import { healthApi } from '@/api/tools'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatusTag } from '@/components/ui/status-tag'
import { useActiveConnection } from '@/hooks/useActiveConnection'
import { useConnections } from '@/hooks/useConnections'
import { useConversation } from '@/hooks/useConversations'
import { useTheme } from '@/lib/theme'
import { S } from '@/lib/strings'
import { navItems } from '@/lib/nav'

/** Top bar: menu (mobile) · breadcrumb · backend/LLM status · active connection · theme. */
export function HeaderBar({ onMenu }: { onMenu: () => void }) {
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-3 md:px-4">
      <Button
        variant="ghost"
        size="icon-sm"
        className="md:hidden"
        onClick={onMenu}
        aria-label={S.nav.openMenu}
      >
        <Menu />
      </Button>
      <Breadcrumb />
      <div className="ml-auto flex items-center gap-2">
        <SystemStatus />
        <ConnectionSwitcher />
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
    </header>
  )
}

function Breadcrumb() {
  const { pathname } = useLocation()
  const { conversationId } = useParams()
  const conversation = useConversation(conversationId)
  const section = navItems.find((n) => pathname.startsWith(n.to))
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-sm">
      <span className="hidden text-muted-foreground sm:inline">{S.app.name}</span>
      {section && (
        <>
          <ChevronRight aria-hidden className="hidden size-3.5 text-muted-foreground sm:inline" />
          {conversationId ? (
            <Link to={section.to} className="text-muted-foreground hover:text-foreground">
              {section.label}
            </Link>
          ) : (
            <span className="font-medium">{section.label}</span>
          )}
        </>
      )}
      {conversationId && (
        <>
          <ChevronRight aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium" title={conversation.data?.title}>
            {conversation.data?.title || S.chat.untitled}
          </span>
        </>
      )}
    </nav>
  )
}

function SystemStatus() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await healthApi.get()).data,
    refetchInterval: 30_000,
    retry: false,
  })
  if (health.isPending) return null
  if (health.isError)
    return (
      <StatusTag tone="danger" dot>
        {S.header.backend}: {S.header.offline}
      </StatusTag>
    )
  return (
    <span className="hidden items-center gap-1.5 lg:flex">
      <StatusTag tone="success" dot title={`v${health.data.version}`}>
        {S.header.backend}: {S.header.online}
      </StatusTag>
      <StatusTag tone="neutral">
        {S.header.llm}: <span className="font-mono">{health.data.llm_provider}</span>
      </StatusTag>
    </span>
  )
}

function ConnectionSwitcher() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { data } = useConnections()
  const { activeConnectionId, setActiveConnectionId, connectedConnections } =
    useActiveConnection(data)
  if (!connectedConnections.length) {
    return (
      <Link to="/connect" className="hidden sm:block">
        <StatusTag tone="warning" dot>
          {S.header.noConnection}
        </StatusTag>
      </Link>
    )
  }
  const active = connectedConnections.find((c) => c.id === activeConnectionId)
  return (
    <Select
      value={activeConnectionId ?? ''}
      onValueChange={(v) => {
        if (!v) return
        setActiveConnectionId(String(v))
        if (pathname.startsWith('/chat/')) navigate('/chat')
      }}
    >
      <SelectTrigger size="sm" className="max-w-56 min-w-36" aria-label={S.header.connection}>
        <SelectValue>
          <span className="flex min-w-0 items-center gap-1.5">
            <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-success" />
            <span className="truncate">{active?.name ?? S.chat.selectConnection}</span>
            {active && (
              <span className="hidden font-mono text-xs text-muted-foreground md:inline">
                {active.region}
              </span>
            )}
          </span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {connectedConnections.map((c) => (
          <SelectItem key={c.id} value={c.id}>
            {c.name} · <span className="font-mono text-xs">{c.account_id ?? '—'}</span> ·{' '}
            <span className="font-mono text-xs">{c.region}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
