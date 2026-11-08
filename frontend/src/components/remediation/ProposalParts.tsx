import { Loader2 } from 'lucide-react'
import type { Proposal, ProposalStatus } from '@/api/types'
import { DescriptionList } from '@/components/layout/Panel'
import { StatusTag, type Tone } from '@/components/ui/status-tag'
import { Mono, TBody, THead, Table, Td, Th, Tr } from '@/components/ui/table'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'

const statusTone: Record<ProposalStatus, Tone> = {
  PENDING_APPROVAL: 'warning',
  APPROVED: 'info',
  EXECUTING: 'info',
  SUCCEEDED: 'success',
  REJECTED: 'neutral',
  EXPIRED: 'neutral',
  SUPERSEDED: 'neutral',
  STALE: 'warning',
  FAILED: 'danger',
  VERIFY_FAILED: 'danger',
  ROLLED_BACK: 'neutral',
}

const riskTone: Record<string, Tone> = { low: 'success', medium: 'warning', high: 'danger' }

export function ProposalStatusTag({ status }: { status: ProposalStatus }) {
  const running = status === 'APPROVED' || status === 'EXECUTING'
  return (
    <StatusTag tone={statusTone[status]} dot={!running}>
      {running && <Loader2 className="animate-spin" aria-hidden />}
      {S.remediation.statuses[status] ?? status}
    </StatusTag>
  )
}

export function RiskTag({ risk }: { risk: string }) {
  return (
    <StatusTag tone={riskTone[risk] ?? 'neutral'}>{S.remediation.risks[risk] ?? risk}</StatusTag>
  )
}

/** What the user approves: before/after table + impact, risk, undo, verification. */
export function ProposalPreview({ proposal: p }: { proposal: Proposal }) {
  const t = S.remediation
  return (
    <div className="space-y-3">
      {p.preview.changes.length > 0 && (
        <div className="rounded-md border">
          <Table>
            <THead>
              <Tr>
                <Th>{t.change}</Th>
                <Th>{t.before}</Th>
                <Th>{t.after}</Th>
              </Tr>
            </THead>
            <TBody>
              {p.preview.changes.map((c, i) => (
                <Tr key={i}>
                  <Td className="font-medium">{c.field}</Td>
                  <Td>
                    <Mono>{c.before}</Mono>
                  </Td>
                  <Td>
                    <Mono className="text-success">{c.after}</Mono>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </div>
      )}
      <DescriptionList
        items={[
          { label: t.impact, value: p.preview.impact },
          { label: t.risk, value: <RiskTag risk={p.preview.risk} /> },
          { label: t.undo, value: p.preview.rollback },
          { label: t.verify, value: p.preview.verify },
          { label: t.params, value: <Mono>{JSON.stringify(p.params)}</Mono> },
        ]}
      />
    </div>
  )
}

/** Outcome + audit trail of a decided proposal. */
export function ProposalOutcome({ proposal: p }: { proposal: Proposal }) {
  const t = S.remediation
  return (
    <div className="space-y-3">
      {p.error && (
        <p
          role="alert"
          className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger"
        >
          {p.error}
        </p>
      )}
      {p.verification && (
        <p
          className={
            p.verification.ok
              ? 'rounded-md border border-success-border bg-success-bg px-3 py-2 text-success'
              : 'rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger'
          }
        >
          <span className="font-medium">{t.verify}:</span> {p.verification.details}
        </p>
      )}
      <div className="rounded-md border">
        <Table>
          <THead>
            <Tr>
              <Th>{t.history}</Th>
              <Th>{t.colStatus}</Th>
              <Th>Note</Th>
            </Tr>
          </THead>
          <TBody>
            {p.history.map((h, i) => (
              <Tr key={i}>
                <Td className="tabular whitespace-nowrap text-muted-foreground">
                  {formatTime(h.at)}
                </Td>
                <Td>
                  <ProposalStatusTag status={h.status} />
                </Td>
                <Td>{h.note}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </div>
    </div>
  )
}
