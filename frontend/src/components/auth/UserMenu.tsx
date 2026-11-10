import { LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useSession } from '@/hooks/useAuth'
import { authEnabled, signOut } from '@/lib/auth'
import { S } from '@/lib/strings'

/** Header: who is signed in + sign out (nothing without sign-in, AUTH_MODE=none). */
export function UserMenu() {
  const { signedIn, user } = useSession()
  if (!authEnabled() || !signedIn) return null
  const name = user?.email ?? user?.username ?? ''
  return (
    <div className="flex items-center gap-1">
      <span
        className="hidden max-w-44 truncate text-xs text-muted-foreground md:inline"
        title={`${S.auth.signedInAs} ${name}`}
      >
        {name}
      </span>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={S.auth.signOut}
        title={S.auth.signOut}
        onClick={signOut}
      >
        <LogOut />
      </Button>
    </div>
  )
}
