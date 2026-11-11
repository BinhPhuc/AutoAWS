import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { S } from '@/lib/strings'
import { HeaderBar } from './HeaderBar'
import { Sidebar } from './Sidebar'

const COLLAPSED_KEY = 'autoaws.sidebarCollapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

/** Dashboard shell: dark sidebar + header bar + page area (same on every route). */
export function AppShell() {
  const [open, setOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)

  const toggle = () =>
    setCollapsed((v) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, v ? '0' : '1')
      } catch {
        /* per-viewer convenience only */
      }
      return !v
    })

  return (
    <div className="flex h-dvh w-full bg-background text-foreground">
      <a
        href="#main"
        className="sr-only z-50 rounded-sm bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <aside
        className={cn(
          'hidden shrink-0 transition-[width] duration-200 md:block',
          collapsed ? 'w-16' : 'w-52',
        )}
      >
        <Sidebar collapsed={collapsed} onToggle={toggle} />
      </aside>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-60 border-0 p-0" showCloseButton>
          <SheetTitle className="sr-only">{S.nav.openMenu}</SheetTitle>
          <Sidebar onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <HeaderBar onMenu={() => setOpen(true)} />
        <main id="main" className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
