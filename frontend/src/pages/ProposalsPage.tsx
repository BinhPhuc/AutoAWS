import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, ShieldCheck } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import { Panel } from '@/components/layout/Panel'
import { EmptyState, PageError, PageLoading } from '@/components/layout/PageState'
import { ProposalCard } from '@/components/remediation/ProposalCard'
import { ProposalStatusTag } from '@/components/remediation/ProposalParts'
import { Button } from '@/components/ui/button'
import { Mono, TBody, THead, Table, Td, Th, Tr } from '@/components/ui/table'
import { useProposals } from '@/hooks/useProposals'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'

/** Every proposal of every conversation: approve from here too, see the audit trail. */
export function ProposalsPage() {
  const t = S.remediation
  const proposals = useProposals('all')
  const [open, setOpen] = useState<string | null>(null)
  const pending = proposals.data?.filter((p) => p.status === 'PENDING_APPROVAL').length ?? 0

  return (
    <PageBody>
      <PageHeader title={t.pageTitle} description={t.subtitle} />
      <Panel
        title={t.pageTitle}
        flush
        extra={
          proposals.data && (
            <span className="tabular text-xs text-muted-foreground">
              {proposals.data.length} total · {pending}{' '}
              {S.remediation.statuses.PENDING_APPROVAL.toLowerCase()}
            </span>
          )
        }
      >
        {proposals.isPending ? (
          <PageLoading />
        ) : proposals.isError ? (
          <PageError error={proposals.error} onRetry={() => void proposals.refetch()} />
        ) : proposals.data.length === 0 ? (
          <EmptyState
            icon={<ShieldCheck className="size-8" />}
            title={t.empty}
            body={t.emptyHint}
          />
        ) : (
          <Table>
            <THead>
              <Tr>
                <Th className="w-8">
                  <span className="sr-only">{S.connections.details}</span>
                </Th>
                <Th>{t.colStatus}</Th>
                <Th>{t.colAction}</Th>
                <Th>{t.colSummary}</Th>
                <Th>{t.colCreated}</Th>
                <Th>{t.colConversation}</Th>
              </Tr>
            </THead>
            <TBody>
              {proposals.data.map((p) => (
                <Fragment key={p.id}>
                  <Tr className="[&>td]:align-middle">
                    <Td>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        aria-expanded={open === p.id}
                        aria-label={`${S.connections.details}: ${p.id}`}
                        onClick={() => setOpen(open === p.id ? null : p.id)}
                      >
                        {open === p.id ? <ChevronDown /> : <ChevronRight />}
                      </Button>
                    </Td>
                    <Td className="whitespace-nowrap">
                      <ProposalStatusTag status={p.status} />
                    </Td>
                    <Td>
                      <Mono className="whitespace-nowrap">{p.action}</Mono>
                      {p.kind === 'rollback' && (
                        <span className="block text-xs text-warning">
                          {t.rollbackOf(p.parent_id ?? '')}
                        </span>
                      )}
                    </Td>
                    <Td>{p.preview.summary}</Td>
                    <Td className="tabular whitespace-nowrap text-muted-foreground">
                      {formatTime(p.created_at)}
                    </Td>
                    <Td>
                      <Link
                        to={`/chat/${p.conversation_id}`}
                        className="text-primary hover:underline"
                      >
                        {t.open}
                      </Link>
                    </Td>
                  </Tr>
                  {open === p.id && (
                    <tr className="border-b bg-muted/40">
                      <td />
                      <td colSpan={5} className="px-3 py-3">
                        {/* w-0 + min-w-full: fills the cell without widening the columns above. */}
                        <div className="w-0 min-w-full">
                          <ProposalCard id={p.id} />
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </TBody>
          </Table>
        )}
      </Panel>
    </PageBody>
  )
}
