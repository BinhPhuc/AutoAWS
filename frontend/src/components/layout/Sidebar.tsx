import { NavLink } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePendingProposals } from '@/hooks/useProposals'
import { navItems } from '@/lib/nav'
import { S } from '@/lib/strings'

/** Dark navigation column (stays dark in both themes). Primary navigation only. */
export function Sidebar({
  collapsed = false,
  onToggle,
  onNavigate,
}: {
  collapsed?: boolean
  onToggle?: () => void
  onNavigate?: () => void
}) {
  const pending = usePendingProposals()
  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div
        className={cn(
          'flex h-12 shrink-0 items-center gap-2.5 border-b border-sidebar-border',
          collapsed ? 'justify-center px-2' : 'px-4',
        )}
      >
        <span
          aria-hidden
          className="flex size-7 shrink-0 items-center justify-center rounded-sm bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground"
        >
          AA
        </span>
        {!collapsed && (
          <span className="truncate text-[15px] font-semibold text-sidebar-accent-foreground">
            {S.app.name}
          </span>
        )}
      </div>

      <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto py-3">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              cn(
                'mx-2 flex h-10 items-center gap-3 rounded-sm px-3 text-sm transition-colors',
                'hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                'focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none',
                collapsed && 'justify-center px-0',
                isActive &&
                  'bg-sidebar-primary text-sidebar-primary-foreground hover:bg-sidebar-primary',
              )
            }
          >
            <span className="relative shrink-0">
              <Icon className="size-4" aria-hidden />
              {collapsed && to === '/proposals' && pending > 0 && (
                <span
                  aria-hidden
                  className="absolute -top-1 -right-1 size-2 rounded-full bg-warning-border"
                />
              )}
            </span>
            {collapsed ? <span className="sr-only">{label}</span> : <span>{label}</span>}
            {to === '/proposals' && pending > 0 && (
              <span
                className={cn(
                  'tabular ml-auto rounded-sm bg-warning-bg px-1.5 text-xs font-semibold text-warning',
                  collapsed && 'sr-only',
                )}
              >
                {pending}
                <span className="sr-only"> {S.remediation.waiting}</span>
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="shrink-0 border-t border-sidebar-border p-2">
        {!collapsed && (
          <p className="flex items-center gap-1.5 px-2 pb-2 text-xs">
            <ShieldCheck className="size-3.5" aria-hidden />
            {S.nav.readOnly}
          </p>
        )}
        {onToggle && (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? S.nav.expand : S.nav.collapse}
            className="flex h-8 w-full cursor-pointer items-center justify-center rounded-sm hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none"
          >
            {collapsed ? (
              <PanelLeftOpen className="size-4" />
            ) : (
              <PanelLeftClose className="size-4" />
            )}
          </button>
        )}
      </div>
    </div>
  )
}
