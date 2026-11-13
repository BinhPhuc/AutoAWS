import { ClipboardCheck, MessageSquare, Plug, Settings2, ShieldCheck, Wrench } from 'lucide-react'
import { S } from '@/lib/strings'

/** Primary navigation (sidebar + breadcrumb). `admin`: shown to admins only. */
export const navItems = [
  { to: '/chat', label: S.nav.chat, icon: MessageSquare, end: false, admin: false },
  { to: '/proposals', label: S.nav.proposals, icon: ShieldCheck, end: true, admin: false },
  { to: '/connect', label: S.nav.connect, icon: Plug, end: true, admin: false },
  { to: '/tools', label: S.nav.tools, icon: Wrench, end: true, admin: false },
  { to: '/checklist', label: S.nav.checklist, icon: ClipboardCheck, end: true, admin: false },
  { to: '/admin', label: S.nav.admin, icon: Settings2, end: true, admin: true },
]
