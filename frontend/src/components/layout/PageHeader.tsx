import { cn } from '@/lib/utils'

/** Title row at the top of every page: title, one-line description, page actions. */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0 space-y-0.5">
        <h1 className="text-lg font-semibold tracking-tight [text-wrap:balance]">{title}</h1>
        {description && <p className="max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Standard scrollable page body: same gutters and max width everywhere. */
export function PageBody({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className="h-full overflow-y-auto">
      <div className={cn('mx-auto w-full max-w-7xl space-y-4 p-4 md:p-6', className)}>
        {children}
      </div>
    </div>
  )
}
