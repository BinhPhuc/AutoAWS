import { useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { S } from '@/lib/strings'
import { Sidebar } from './Sidebar'

export function AppShell() {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  return (
    <div className="flex h-dvh w-full bg-background text-foreground">
      {/* Desktop sidebar */}
      <aside className="hidden w-72 shrink-0 border-r bg-sidebar text-sidebar-foreground md:flex md:flex-col">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-72 p-0" showCloseButton>
          <SheetTitle className="sr-only">{S.nav.openMenu}</SheetTitle>
          <Sidebar onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center gap-2 border-b px-3 md:hidden">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setOpen(true)}
            aria-label={S.nav.openMenu}
          >
            <Menu />
          </Button>
          <span className="font-heading font-medium">{S.app.name}</span>
          <span className="text-xs text-muted-foreground">{routeTitle(location.pathname)}</span>
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function routeTitle(path: string) {
  if (path.startsWith('/chat')) return S.nav.chat
  if (path.startsWith('/checklist')) return S.nav.checklist
  if (path.startsWith('/connect')) return S.nav.connect
  return ''
}
