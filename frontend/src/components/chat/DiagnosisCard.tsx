import { AlertTriangle, CheckCircle2, CircleHelp, Lightbulb, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { Confidence, DiagnosisAnswer, Evidence, RootCause } from '@/api/types'
import { useToolLookup } from '@/hooks/useTools'
import { S } from '@/lib/strings'
import { cn } from '@/lib/utils'
import { CopyButton } from '@/components/connections/CloudFormationSnippet'

const confidenceClass: Record<Confidence, string> = {
  high: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  medium: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  low: 'bg-muted text-muted-foreground',
}

function ConfidenceBadge({ value }: { value: Confidence }) {
  return (
    <Badge variant="outline" className={cn('border-transparent', confidenceClass[value])}>
      {S.diagnosis.confidence[value] ?? value}
    </Badge>
  )
}

export function DiagnosisCard({ answer }: { answer: DiagnosisAnswer }) {
  const t = S.diagnosis
  const causes = answer.root_causes ?? []

  return (
    <Card data-testid="diagnosis-card">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-start justify-between gap-2">
          <span className="leading-snug">{answer.summary}</span>
          <ConfidenceBadge value={answer.confidence} />
        </CardTitle>
        {answer.limit_reached && (
          <p
            role="status"
            className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300 [&_svg]:size-3.5"
          >
            <AlertTriangle />
            {t.limitReached[answer.limit_reached] ?? answer.limit_reached}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-5">
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
            <ol className="list-decimal space-y-1 pl-5 leading-relaxed">
              {answer.fix_steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </Section>
        )}

        {answer.unverified.length > 0 && (
          <Section icon={<CircleHelp />} title={t.notVerified}>
            <ul className="space-y-2">
              {answer.unverified.map((u, i) => (
                <li key={i} className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span>{u.text}</span>
                    <Badge
                      variant="outline"
                      className="border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-300"
                    >
                      {t.checkManually}
                    </Badge>
                  </div>
                  {u.how_to_check && (
                    <div className="flex items-center gap-2">
                      <code className="rounded bg-muted px-2 py-1 font-mono text-xs break-all">
                        {u.how_to_check}
                      </code>
                      <CopyButton text={u.how_to_check} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}
      </CardContent>
    </Card>
  )
}

function RootCauseItem({ cause, index }: { cause: RootCause; index: number | null }) {
  return (
    <li className="space-y-2" data-testid="root-cause">
      <div className="flex flex-wrap items-start gap-2">
        {index !== null && (
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
            {index}
          </span>
        )}
        <p className="flex-1 leading-relaxed">{cause.statement}</p>
        <ConfidenceBadge value={cause.confidence} />
      </div>
      {cause.evidence.length > 0 && (
        <ul className="space-y-1.5 border-l pl-3">
          {cause.evidence.map((e, i) => (
            <EvidenceItem key={i} evidence={e} />
          ))}
        </ul>
      )}
    </li>
  )
}

function EvidenceItem({ evidence: e }: { evidence: Evidence }) {
  const lookup = useToolLookup()
  const t = S.diagnosis
  // Older answers carry only `verified`; the server sets `verification` for new ones.
  const verification = e.verification ?? (e.verified ? 'read' : 'inferred')
  return (
    <li className="flex flex-wrap items-start gap-x-2 gap-y-1">
      <span className="leading-relaxed">{e.text}</span>
      {e.resource_id && (
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs break-all">
          {e.resource_id}
          {e.value ? ` = ${e.value}` : ''}
        </code>
      )}
      <span className="flex items-center gap-1">
        <Badge variant="outline" className="font-mono text-[10px]">
          {lookup(e.source).label}
        </Badge>
        {verification === 'read' && (
          <Badge
            variant="outline"
            className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
          >
            <CheckCircle2 />
            {t.verifiedBadge}
          </Badge>
        )}
        {verification === 'inferred' && (
          <Badge variant="outline" className="text-muted-foreground">
            {t.inferredBadge}
          </Badge>
        )}
        {verification === 'not_found' && (
          <Badge
            variant="outline"
            title={t.notFoundHint}
            className="border-transparent bg-red-500/15 text-red-700 dark:text-red-300"
          >
            <AlertTriangle />
            {t.notFoundBadge}
          </Badge>
        )}
      </span>
    </li>
  )
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-1.5">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase [&_svg]:size-3.5">
        {icon}
        {title}
      </h4>
      <div className="text-sm">{children}</div>
    </section>
  )
}
