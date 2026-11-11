import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { LogIn } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/layout/PageState'
import { useAuthConfig, useSession } from '@/hooks/useAuth'
import { signIn } from '@/lib/auth'
import { S } from '@/lib/strings'

/** Shows the app only to a signed-in user when the backend runs AUTH_MODE=cognito. */
export function AuthGate({ children }: { children: ReactNode }) {
  const config = useAuthConfig()
  const { signedIn } = useSession()
  const queryClient = useQueryClient()

  // Signed out (or the session expired): forget the previous user's cached data
  useEffect(() => {
    if (config.data?.mode === 'cognito' && !signedIn) queryClient.clear()
  }, [config.data?.mode, signedIn, queryClient])

  if (config.isPending) return <PageLoading />
  if (config.data?.mode !== 'cognito' || signedIn) return <>{children}</>
  return <SignInPage />
}

export function SignInPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-sm border bg-card p-6 shadow-xs">
        <div className="mb-4 flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex size-8 items-center justify-center rounded-sm bg-primary text-xs font-bold text-primary-foreground"
          >
            AA
          </span>
          <span className="text-base font-semibold">{S.app.name}</span>
        </div>
        <h1 className="text-lg font-semibold">{S.auth.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{S.auth.body}</p>
        <Button className="mt-5 w-full" onClick={() => void signIn()}>
          <LogIn />
          {S.auth.signIn}
        </Button>
        <p className="mt-3 text-xs text-muted-foreground">{S.auth.newHere}</p>
      </div>
    </main>
  )
}
