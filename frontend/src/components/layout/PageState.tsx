import { AlertTriangle, Loader2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { S } from '@/lib/strings'

export function PageLoading({ label = S.common.loading }: { label?: string }) {
  return (
    <div className="flex h-full min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
      {label}
    </div>
  )
}

export function PageError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? error.status_code === 0
        ? S.common.networkError
        : error.message
      : S.common.somethingWentWrong
  return (
    <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 text-center">
      <AlertTriangle className="size-6 text-destructive" />
      <p className="text-sm text-muted-foreground">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {S.common.retry}
        </Button>
      )}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: React.ReactNode
  title: string
  body?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex h-full min-h-60 flex-col items-center justify-center gap-3 px-6 text-center">
      {icon && <div className="text-muted-foreground">{icon}</div>}
      <h2 className="font-heading text-lg font-medium">{title}</h2>
      {body && <p className="max-w-md text-sm text-muted-foreground">{body}</p>}
      {action}
    </div>
  )
}
