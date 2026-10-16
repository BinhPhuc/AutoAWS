import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import type { Connection, ConnectionStatus } from '@/api/types'
import { S } from '@/lib/strings'
import { cn } from '@/lib/utils'

export function StatusBadge({
  status,
  className,
}: {
  status: ConnectionStatus
  className?: string
}) {
  const map: Record<ConnectionStatus, { label: string; cls: string }> = {
    connected: {
      label: S.status.connected,
      cls: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
    },
    pending: { label: S.status.pending, cls: 'bg-amber-500/15 text-amber-700 dark:text-amber-300' },
    failed: { label: S.status.failed, cls: 'bg-destructive/10 text-destructive' },
  }
  const { label, cls } = map[status]
  return (
    <Badge variant="outline" className={cn('border-transparent', cls, className)}>
      <span
        className={cn(
          'size-1.5 rounded-full',
          status === 'connected' && 'bg-emerald-500',
          status === 'pending' && 'bg-amber-500',
          status === 'failed' && 'bg-destructive',
        )}
      />
      {label}
    </Badge>
  )
}

/** Compact "current connection" card at the bottom of the sidebar. */
export function ConnectionBadge({ connection }: { connection?: Connection }) {
  if (!connection) {
    return (
      <Link
        to="/connect"
        className="block rounded-md border border-dashed p-2 text-xs text-muted-foreground hover:bg-sidebar-accent"
      >
        {S.chat.noConnectedConnection}
      </Link>
    )
  }
  return (
    <Link to="/connect" className="block rounded-md border p-2 hover:bg-sidebar-accent">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium">{connection.name}</span>
        <StatusBadge status={connection.status} />
      </div>
      <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
        {connection.account_id ?? '—'} · {connection.region}
      </div>
    </Link>
  )
}
