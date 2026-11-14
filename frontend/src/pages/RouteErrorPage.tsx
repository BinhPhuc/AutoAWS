import { useState } from 'react'
import { isRouteErrorResponse, useRouteError } from 'react-router-dom'
import { ChevronRight, TriangleAlert } from 'lucide-react'
import { CopyButton } from '@/components/connections/CloudFormationSnippet'
import { ErrorView } from '@/components/layout/ErrorView'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { S } from '@/lib/strings'
import { cn } from '@/lib/utils'

/** Pulls a readable message (and, in dev, the stack) out of whatever was thrown. */
export function describeError(error: unknown): string {
  if (isRouteErrorResponse(error)) {
    const body = typeof error.data === 'string' ? error.data : ''
    return [`${error.status} ${error.statusText}`.trim(), body].filter(Boolean).join('\n')
  }
  if (error instanceof Error) {
    const stack = import.meta.env.DEV && error.stack ? `\n\n${error.stack}` : ''
    return `${error.name}: ${error.message}${stack}`
  }
  return typeof error === 'string' ? error : (JSON.stringify(error, null, 2) ?? String(error))
}

function ErrorPage({ standalone }: { standalone: boolean }) {
  const error = useRouteError()
  const [open, setOpen] = useState(false)
  const t = S.errors.app

  if (isRouteErrorResponse(error) && error.status === 404) {
    return <NotFoundPage standalone={standalone} />
  }

  const details = describeError(error)
  return (
    <ErrorView
      standalone={standalone}
      reload
      title={t.title}
      description={t.body}
      hero={
        <div className="flex size-14 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
          <TriangleAlert className="size-7" strokeWidth={1.75} />
        </div>
      }
    >
      <Collapsible open={open} onOpenChange={setOpen} className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <CollapsibleTrigger className="flex items-center gap-1.5 rounded-md px-1 py-1 text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50">
            <ChevronRight className={cn('size-3.5 transition-transform', open && 'rotate-90')} />
            {t.details}
          </CollapsibleTrigger>
          <CopyButton text={details} label={t.copyDetails} />
        </div>
        <CollapsibleContent>
          <pre className="max-h-64 overflow-auto rounded-lg bg-muted px-3 py-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
            {details}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </ErrorView>
  )
}

/** errorElement for page routes: renders inside AppShell, so the sidebar stays. */
export function RouteErrorPage() {
  return <ErrorPage standalone={false} />
}

/** errorElement for the root route: AppShell itself failed, so render a full-screen page. */
export function RootErrorPage() {
  return <ErrorPage standalone />
}
