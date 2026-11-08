import { cn } from '@/lib/utils'

/** White bordered panel with an optional title bar — the only container style used on pages. */
export function Panel({
  title,
  extra,
  children,
  className,
  bodyClassName,
  flush = false,
}: {
  title?: React.ReactNode
  /** Right side of the title bar: actions, counters, tags. */
  extra?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
  /** No body padding (tables that touch the panel edges). */
  flush?: boolean
}) {
  return (
    <section className={cn('rounded-md border bg-card text-card-foreground', className)}>
      {(title || extra) && (
        <header className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b px-4 py-2">
          <h2 className="text-sm font-semibold">{title}</h2>
          {extra && <div className="flex flex-wrap items-center gap-2">{extra}</div>}
        </header>
      )}
      <div className={cn(!flush && 'p-4', bodyClassName)}>{children}</div>
    </section>
  )
}

/** Small label/value grid inside panels (like a "Overview" key-value block). */
export function DescriptionList({
  items,
  className,
}: {
  items: { label: string; value: React.ReactNode }[]
  className?: string
}) {
  return (
    <dl className={cn('grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm', className)}>
      {items.map((it) => (
        <div key={it.label} className="contents">
          <dt className="text-muted-foreground">{it.label}</dt>
          <dd className="min-w-0 [overflow-wrap:anywhere]">{it.value}</dd>
        </div>
      ))}
    </dl>
  )
}
