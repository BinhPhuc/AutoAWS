import { Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, Home, RotateCw } from 'lucide-react'
import { Button, buttonVariants } from '@/components/ui/button'
import { S } from '@/lib/strings'
import { cn } from '@/lib/utils'

/**
 * Shared frame for the 404 page and the crash page: a hero slot (the memorable element),
 * a title + explanation, optional content, and the recovery actions.
 */
export function ErrorView({
  hero,
  title,
  description,
  children,
  reload = false,
  standalone = false,
}: {
  hero: React.ReactNode
  title: string
  description: string
  children?: React.ReactNode
  /** Show "Reload page" instead of "Go back" (for crashes, where going back may crash again). */
  reload?: boolean
  /** Rendered outside AppShell (no sidebar): fill the viewport and own the background. */
  standalone?: boolean
}) {
  const navigate = useNavigate()
  return (
    <div
      className={cn(
        'overflow-y-auto',
        standalone ? 'h-dvh bg-background text-foreground' : 'h-full',
      )}
    >
      <div className="mx-auto flex min-h-full w-full max-w-xl flex-col justify-center gap-8 px-6 py-12">
        <div className="space-y-4">
          {hero}
          <div className="space-y-2">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          </div>
        </div>

        {children}

        <div className="flex flex-wrap gap-2">
          <Link to="/" className={buttonVariants({ size: 'lg' })}>
            <Home />
            {S.errors.backHome}
          </Link>
          {reload ? (
            <Button variant="outline" size="lg" onClick={() => window.location.reload()}>
              <RotateCw />
              {S.errors.reload}
            </Button>
          ) : (
            <Button variant="outline" size="lg" onClick={() => navigate(-1)}>
              <ArrowLeft />
              {S.errors.goBack}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
