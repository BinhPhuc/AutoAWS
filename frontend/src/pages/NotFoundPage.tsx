import { Link, useLocation } from 'react-router-dom'
import { Unplug } from 'lucide-react'
import { ErrorView } from '@/components/layout/ErrorView'
import { navItems } from '@/lib/nav'
import { S } from '@/lib/strings'

/** Catch-all route. Renders inside AppShell so the sidebar stays available. */
export function NotFoundPage({ standalone = false }: { standalone?: boolean }) {
  const { pathname, search } = useLocation()
  const t = S.errors.notFound

  return (
    <ErrorView
      standalone={standalone}
      title={t.title}
      description={t.body}
      hero={
        <div
          role="img"
          aria-label={t.code}
          className="flex items-center gap-1 font-heading text-8xl leading-none font-semibold tracking-tighter text-foreground/15 select-none"
        >
          <span aria-hidden>4</span>
          <Unplug aria-hidden className="size-[0.7em] text-foreground/30" strokeWidth={1.5} />
          <span aria-hidden>4</span>
        </div>
      }
    >
      <section className="space-y-1.5">
        <h2 className="text-xs font-medium text-muted-foreground">{t.requestedPath}</h2>
        <code className="block overflow-x-auto rounded-lg bg-muted px-3 py-2 font-mono text-xs break-all whitespace-pre-wrap">
          {pathname}
          {search}
        </code>
      </section>

      <section className="space-y-2">
        <h2 className="text-xs font-medium text-muted-foreground">{t.whereTo}</h2>
        <ul className="divide-y overflow-hidden rounded-xl ring-1 ring-foreground/10">
          {navItems.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <Link
                to={to}
                className="flex items-center gap-3 px-3 py-2.5 text-sm transition-colors outline-none hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
              >
                <Icon className="size-4 shrink-0 text-muted-foreground" />
                <span className="flex min-w-0 flex-col sm:flex-row sm:gap-3">
                  <span className="font-medium">{label}</span>
                  <span className="text-muted-foreground">{t.links[to]}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </ErrorView>
  )
}
