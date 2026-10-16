import { CheckCircle2, CircleHelp, Lightbulb, ListChecks, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { DiagnosisAnswer } from '@/api/types'
import { useToolLookup } from '@/hooks/useTools'
import { S } from '@/lib/strings'
import { cn } from '@/lib/utils'
import { CopyButton } from '@/components/connections/CloudFormationSnippet'

const confidenceClass: Record<DiagnosisAnswer['confidence'], string> = {
  high: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  medium: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  low: 'bg-muted text-muted-foreground',
}

export function DiagnosisCard({ answer }: { answer: DiagnosisAnswer }) {
  const lookup = useToolLookup()
  const t = S.diagnosis

  return (
    <Card data-testid="diagnosis-card">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-start justify-between gap-2">
          <span className="leading-snug">{answer.summary}</span>
          <Badge
            variant="outline"
            className={cn('border-transparent', confidenceClass[answer.confidence])}
          >
            {t.confidence[answer.confidence] ?? answer.confidence}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <Section icon={<Search />} title={t.rootCause}>
          <p className="leading-relaxed">{answer.cause}</p>
        </Section>

        {answer.evidence.length > 0 && (
          <Section icon={<ListChecks />} title={t.evidence}>
            <ul className="space-y-1.5">
              {answer.evidence.map((e, i) => (
                <li key={i} className="flex flex-wrap items-start gap-x-2 gap-y-1">
                  <span className="leading-relaxed">{e.text}</span>
                  <span className="flex items-center gap-1">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {lookup(e.source).label}
                    </Badge>
                    {e.verified && (
                      <Badge
                        variant="outline"
                        className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                      >
                        <CheckCircle2 />
                        {t.verifiedBadge}
                      </Badge>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

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
                      <code className="rounded bg-muted px-2 py-1 font-mono text-xs">
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
