import { ClipboardCheck } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import { Panel } from '@/components/layout/Panel'
import { EmptyState } from '@/components/layout/PageState'
import { StatusTag } from '@/components/ui/status-tag'
import { S } from '@/lib/strings'

export function ChecklistPage() {
  const t = S.checklist
  return (
    <PageBody>
      <PageHeader
        title={t.title}
        description={t.subtitle}
        actions={<StatusTag tone="neutral">{t.comingSoon}</StatusTag>}
      />
      <Panel>
        <EmptyState
          icon={<ClipboardCheck className="size-8" />}
          title={t.comingSoon}
          body={t.body}
        />
      </Panel>
    </PageBody>
  )
}
