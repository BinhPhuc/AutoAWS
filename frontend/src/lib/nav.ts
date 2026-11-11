import { ClipboardCheck, MessageSquare, Plug, ShieldCheck, Wrench } from 'lucide-react'
import { S } from '@/lib/strings'

/** Primary navigation (sidebar + breadcrumb). */
export const navItems = [
  { to: '/chat', label: S.nav.chat, icon: MessageSquare, end: false },
  { to: '/proposals', label: S.nav.proposals, icon: ShieldCheck, end: true },
  { to: '/tools', label: S.nav.tools, icon: Wrench, end: true },
  { to: '/checklist', label: S.nav.checklist, icon: ClipboardCheck, end: true },
  { to: '/connect', label: S.nav.connect, icon: Plug, end: true },
]
