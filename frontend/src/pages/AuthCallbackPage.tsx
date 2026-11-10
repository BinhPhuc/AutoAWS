import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/layout/PageState'
import { useAuthConfig } from '@/hooks/useAuth'
import { completeSignIn, signIn } from '@/lib/auth'
import { S } from '@/lib/strings'

/** /auth/callback: the Hosted UI comes back here with ?code&state. */
export function AuthCallbackPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const config = useAuthConfig()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!config.isSuccess) return
    completeSignIn(params)
      .then((to) => navigate(to, { replace: true }))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [config.isSuccess, params, navigate])

  if (!error) return <PageLoading label={S.auth.signingIn} />
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 px-4 text-center">
      <AlertTriangle className="size-6 text-destructive" />
      <h1 className="font-semibold">{S.auth.failed}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{error}</p>
      <Button variant="outline" size="sm" onClick={() => void signIn('/')}>
        {S.auth.tryAgain}
      </Button>
    </main>
  )
}
