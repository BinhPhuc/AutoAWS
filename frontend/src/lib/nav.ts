import { ClipboardCheck, MessageSquare, Plug } from 'lucide-react'
import { S } from '@/lib/strings'

/** Top-level destinations, shared by the sidebar and the error pages. */
export const navItems = [
  { to: '/connect', label: S.nav.connect, icon: Plug, end: true },
  { to: '/chat', label: S.nav.chat, icon: MessageSquare, end: false },
  { to: '/checklist', label: S.nav.checklist, icon: ClipboardCheck, end: true },
] as const
