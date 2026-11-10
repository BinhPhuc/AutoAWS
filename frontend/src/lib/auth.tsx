import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { initializeAuth, onSessionEnded, signIn, signOut } from '@/api/auth'
import type { AuthUser } from '@/api/types'
import { Button } from '@/components/ui/button'
import { S } from '@/lib/strings'
import { clearActiveConnection } from '@/hooks/useActiveConnection'

const AuthContext = createContext<AuthUser | null>(null)
const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let active = true
    const unsubscribe = onSessionEnded(() => {
      clearActiveConnection()
      void queryClient.cancelQueries()
      queryClient.clear()
      setUser(null)
    })
    void initializeAuth()
      .then((value) => {
        if (active) setUser(value)
      })
      .catch(() => {
        if (active) setError(S.auth.failed)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      unsubscribe()
    }
  }, [queryClient])
  if (loading || !user)
    return (
      <main className="flex min-h-dvh items-center justify-center bg-background p-6 text-foreground">
        <div className="w-full max-w-sm space-y-5 rounded-xl border bg-card p-8 shadow-sm">
          <p className="text-sm font-semibold text-primary">{S.app.name}</p>
          <h1 className="text-2xl font-semibold">{S.auth.title}</h1>
          <p className="text-sm text-muted-foreground">
            {loading ? S.auth.loading : S.auth.description}
          </p>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {!loading && (
            <Button
              className="w-full"
              disabled={busy}
              onClick={() => {
                setBusy(true)
                void signIn().catch(() => {
                  setError(S.auth.failed)
                  setBusy(false)
                })
              }}
            >
              {S.auth.signIn}
            </Button>
          )}
          {error && (
            <Button
              variant="outline"
              className="w-full"
              onClick={() => window.location.assign('/')}
            >
              {S.auth.retry}
            </Button>
          )}
        </div>
      </main>
    )
  return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>
}

export function SignOutButton() {
  const user = useAuth()
  if (!user || user.user_id === 'local-dev') return null
  return (
    <Button
      variant="ghost"
      size="sm"
      title={user.username ?? user.user_id}
      onClick={() => {
        void signOut().catch(() => {
          /* local session is already cleared */
        })
      }}
    >
      {S.auth.signOut}
    </Button>
  )
}
