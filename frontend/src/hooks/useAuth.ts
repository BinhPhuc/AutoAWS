import { useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { authApi } from '@/api/auth'
import type { AuthConfig } from '@/api/types'
import { currentUser, isSignedIn, setAuthConfig, subscribe } from '@/lib/auth'

const NO_AUTH: AuthConfig = { mode: 'none', domain: null, client_id: null, scopes: [] }

/** How this deployment signs in (GET /api/auth/config), applied to lib/auth. A backend that
 * cannot be reached is treated as "no sign-in": the pages then show their own errors. */
export function useAuthConfig() {
  return useQuery({
    queryKey: ['auth-config'],
    queryFn: async () => {
      let cfg = NO_AUTH
      try {
        cfg = (await authApi.config()).data
      } catch {
        /* offline backend: fall through */
      }
      setAuthConfig(cfg)
      return cfg
    },
    staleTime: Infinity,
    retry: false,
  })
}

/** Re-renders when the session changes (sign-in, refresh failure, sign-out). */
export function useSession() {
  const signedIn = useSyncExternalStore(subscribe, isSignedIn, () => false)
  return { signedIn, user: signedIn ? currentUser() : null }
}

/** The caller (GET /api/me): who they are and whether they are an admin. */
export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => (await authApi.me()).data,
    staleTime: 5 * 60_000,
    retry: false,
  })
}
