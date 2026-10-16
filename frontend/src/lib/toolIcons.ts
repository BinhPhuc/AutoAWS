import {
  Activity,
  Cloud,
  Globe,
  History,
  Network,
  ScrollText,
  Server,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import type { ToolGroup } from '@/api/types'

/** Icon per tool group. Labels come from GET /api/tools; FE only maps icons. */
export const toolGroupIcons: Record<ToolGroup, LucideIcon> = {
  compute: Server,
  network: Network,
  dns: Globe,
  elb: Cloud,
  metrics: Activity,
  logs: ScrollText,
  cloudtrail: History,
}

export function iconForGroup(group: string | undefined): LucideIcon {
  return (group && toolGroupIcons[group as ToolGroup]) || Wrench
}
