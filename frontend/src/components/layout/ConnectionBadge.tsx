import type { ConnectionStatus } from '@/api/types'
import { StatusTag, type Tone } from '@/components/ui/status-tag'
import { S } from '@/lib/strings'

const tone: Record<ConnectionStatus, Tone> = {
  connected: 'success',
  pending: 'warning',
  failed: 'danger',
}

export function StatusBadge({ status }: { status: ConnectionStatus }) {
  return (
    <StatusTag tone={tone[status]} dot>
      {S.status[status]}
    </StatusTag>
  )
}
