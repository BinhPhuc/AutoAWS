import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  Lightbulb,
  Search,
  ShieldCheck,
} from 'lucide-react'
import type { Confidence, DiagnosisAnswer, Evidence, RootCause } from '@/api/types'
import { Panel } from '@/components/layout/Panel'
import { StatusTag, type Tone } from '@/components/ui/status-tag'
import { Mono, TBody, THead, Table, Td, Th, Tr } from '@/components/ui/table'
import { useToolLookup } from '@/hooks/useTools'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'
import { CopyButton } from '@/components/connections/CloudFormationSnippet'
import { ProposalList } from '@/components/remediation/ProposalCard'
import { useChatActions } from './chatActions'

const confidenceTone: Record<Confidence, Tone> = {
  high: 'success',
  medium: 'warning',
  low: 'neutral',
}

function ConfidenceTag({ value }: { value: Confidence }) {
  return (
    <StatusTag tone={confidenceTone[value]}>{S.diagnosis.confidence[value] ?? value}</StatusTag>
  )
}

export function DiagnosisCard({ answer, time }: { answer: DiagnosisAnswer; time?: string }) {
  const t = S.diagnosis
  const causes = answer.root_causes ?? []
  const proposals = answer.proposals ?? []
  const { followup } = useChatActions()

  return (
    <div data-testid="diagnosis-card">
      <Panel
        title={t.title}
        extra={
          <>
            {time && (
              <span className="tabular text-xs text-muted-foreground">{formatTime(time)}</span>
            )}
            <ConfidenceTag value={answer.confidence} />
          </>
        }
        bodyClassName="space-y-5"
      >
        <p className="text-[15px] leading-relaxed font-medium">{answer.summary}</p>

        {answer.limit_reached && (
          <p
            role="status"
            className="flex items-center gap-2 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-warning"
          >
            <AlertTriangle className="size-4 shrink-0" aria-hidden />
            {t.limitReached[answer.limit_reached] ?? answer.limit_reached}
          </p>
        )}

        <Section
          icon={<Search />}
          title={causes.length > 1 ? t.rootCauses(causes.length) : t.rootCause}
        >
          {causes.length === 0 ? (
            <p className="text-muted-foreground">{t.noRootCause}</p>
          ) : (
            <ol className="space-y-4">
              {causes.map((cause, i) => (
                <RootCauseItem key={i} cause={cause} index={causes.length > 1 ? i + 1 : null} />
              ))}
            </ol>
          )}
        </Section>

        {answer.fix_steps.length > 0 && (
          <Section icon={<Lightbulb />} title={t.howToFix}>
            <ol className="list-decimal space-y-1 pl-5 leading-relaxed marker:text-muted-foreground">
              {answer.fix_steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </Section>
        )}

        {proposals.length > 0 && (
          <Section icon={<ShieldCheck />} title={S.remediation.title}>
            <ProposalList refs={proposals} onFollowup={followup} />
          </Section>
        )}

        {answer.unverified.length > 0 && (
          <Section
            icon={<CircleHelp />}
            title={t.notVerified}
            extra={<StatusTag tone="warning">{t.checkManually}</StatusTag>}
          >
            <div className="rounded-md border">
              <Table>
                <THead>
                  <Tr>
                    <Th>{t.colWhat}</Th>
                    <Th>{t.colHow}</Th>
                  </Tr>
                </THead>
                <TBody>
                  {answer.unverified.map((u, i) => (
                    <Tr key={i}>
                      <Td className="w-1/2">{u.text}</Td>
                      <Td>
                        {u.how_to_check && (
                          <div className="flex items-start gap-1.5">
                            <code className="min-w-0 flex-1 rounded-sm bg-muted px-2 py-1 font-mono text-xs [overflow-wrap:anywhere]">
                              {u.how_to_check}
                            </code>
                            <CopyButton text={u.how_to_check} />
                          </div>
                        )}
                      </Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            </div>
          </Section>
        )}
      </Panel>
    </div>
  )
}

function RootCauseItem({ cause, index }: { cause: RootCause; index: number | null }) {
  const t = S.diagnosis
  return (
    <li className="space-y-2" data-testid="root-cause">
      <div className="flex items-start gap-2">
        {index !== null && (
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-sm bg-primary text-xs font-semibold text-primary-foreground">
            {index}
          </span>
        )}
        <p className="flex-1 leading-relaxed">{cause.statement}</p>
        <ConfidenceTag value={cause.confidence} />
      </div>
      {cause.evidence.length > 0 && (
        <div className="rounded-md border">
          <Table>
            <THead>
              <Tr>
                <Th>{t.colEvidence}</Th>
                <Th>{t.colSource}</Th>
                <Th>{t.colResource}</Th>
                <Th>{t.colCheck}</Th>
              </Tr>
            </THead>
            <TBody>
              {cause.evidence.map((e, i) => (
                <EvidenceRow key={i} evidence={e} />
              ))}
            </TBody>
          </Table>
        </div>
      )}
    </li>
  )
}

function EvidenceRow({ evidence: e }: { evidence: Evidence }) {
  const lookup = useToolLookup()
  const t = S.diagnosis
  // Older answers carry only `verified`; the server sets `verification` for new ones.
  const verification = e.verification ?? (e.verified ? 'read' : 'inferred')
  return (
    <Tr>
      <Td className="min-w-48">{e.text}</Td>
      <Td className="whitespace-nowrap">
        <span className="block">{lookup(e.source).label}</span>
        <Mono className="text-muted-foreground">{e.source}</Mono>
      </Td>
      <Td>
        {e.resource_id ? (
          <Mono>
            {e.resource_id}
            {e.value ? ` = ${e.value}` : ''}
          </Mono>
        ) : (
          '—'
        )}
      </Td>
      <Td className="whitespace-nowrap">
        {verification === 'read' && (
          <StatusTag tone="success">
            <CheckCircle2 aria-hidden />
            {t.verifiedBadge}
          </StatusTag>
        )}
        {verification === 'inferred' && <StatusTag tone="neutral">{t.inferredBadge}</StatusTag>}
        {verification === 'not_found' && (
          <StatusTag tone="danger" title={t.notFoundHint}>
            <AlertTriangle aria-hidden />
            {t.notFoundBadge}
          </StatusTag>
        )}
      </Td>
    </Tr>
  )
}

function Section({
  icon,
  title,
  extra,
  children,
}: {
  icon: React.ReactNode
  title: string
  extra?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold [&_svg]:size-4 [&_svg]:text-muted-foreground">
          {icon}
          {title}
        </h3>
        {extra}
      </div>
      <div>{children}</div>
    </section>
  )
}
