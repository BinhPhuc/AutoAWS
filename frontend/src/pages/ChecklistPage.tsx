import { ClipboardCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/layout/PageState'
import { S } from '@/lib/strings'

export function ChecklistPage() {
  return (
    <div className="h-full">
      <EmptyState
        icon={<ClipboardCheck className="size-8" />}
        title={S.checklist.title}
        body={S.checklist.body}
        action={<Badge variant="secondary">{S.checklist.comingSoon}</Badge>}
      />
    </div>
  )
}
