import { useState } from 'react'
import { Check, Copy, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useCloudFormation, useCloudFormationPreview } from '@/hooks/useConnections'
import { S } from '@/lib/strings'
import { InstructionText } from './InstructionText'

export function CopyButton({
  text,
  label = S.common.copy,
  accessibleLabel,
}: {
  text: string
  label?: string
  accessibleLabel?: string
}) {
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        type="button"
        aria-label={accessibleLabel}
        variant="outline"
        size="sm"
        onClick={async () => {
          try {
            setFailed(false)
            await navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          } catch {
            setFailed(true)
          }
        }}
      >
        {copied ? <Check /> : <Copy />}
        {copied ? S.common.copied : label}
      </Button>
      {failed && (
        <span role="status" className="text-xs text-destructive">
          {S.common.copyFailed}
        </span>
      )}
    </span>
  )
}

export function CloudFormationSnippet({
  externalId,
  connectionId,
}: {
  externalId?: string
  connectionId?: string
}) {
  const preview = useCloudFormationPreview(externalId ?? '')
  const saved = useCloudFormation(connectionId ?? null)
  const { data, isPending, isError, isFetching, refetch } = connectionId ? saved : preview
  const t = S.connections.cfn

  if (!connectionId && !/^[A-Za-z0-9_+=,.@:/-]{2,1224}$/.test(externalId ?? '')) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {S.connections.form.errors.externalIdInvalid}
      </p>
    )
  }

  if (isPending)
    return (
      <div role="status" className="space-y-2">
        <span>{S.common.loading}</span>
        <Skeleton className="h-32" />
      </div>
    )
  if (isError || !data)
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-destructive">
          {t.loadError}
        </p>
        <Button
          type="button"
          variant="outline"
          disabled={isFetching}
          onClick={() => void refetch()}
        >
          {S.common.retry}
        </Button>
      </div>
    )

  const download = () => {
    const url = URL.createObjectURL(new Blob([data.template_yaml], { type: 'application/yaml' }))
    const link = document.createElement('a')
    link.href = url
    link.download = t.templateFileName
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <section className="min-w-0 space-y-4 text-sm">
      <h3 className="font-semibold">{t.title}</h3>
      <p className="text-muted-foreground">{t.intro}</p>
      <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
        {t.existingRole}
      </p>
      <div className="space-y-3 rounded-md border bg-primary/5 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-xs text-muted-foreground">{t.stackName}</p>
            <code className="font-semibold">{data.stack_name}</code>
          </div>
          <CopyButton text={data.stack_name} accessibleLabel={`${S.common.copy}: ${t.stackName}`} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t.externalId}</p>
            <code className="break-all font-semibold">{data.external_id}</code>
          </div>
          <CopyButton
            text={data.external_id}
            accessibleLabel={`${S.common.copy}: ${t.externalId}`}
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={download}>
          <Download aria-hidden="true" />
          {t.downloadTemplate}
        </Button>
        <CopyButton text={data.template_yaml} label={t.copyTemplate} />
      </div>
      <ol className="list-decimal space-y-3 pl-5 text-muted-foreground">
        {[t.step1, t.step2, t.step3, t.step4, t.step5, t.step6].map((step) => (
          <li key={step}>
            <InstructionText text={step} />
          </li>
        ))}
      </ol>
      <details className="min-w-0 rounded-md border p-3">
        <summary className="cursor-pointer font-medium">{t.showTemplate}</summary>
        <pre
          tabIndex={0}
          aria-label={t.showTemplate}
          className="mt-3 max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed"
        >
          <code>{data.template_yaml}</code>
        </pre>
      </details>
      <a
        href="https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html"
        target="_blank"
        rel="noreferrer"
        className="inline-block py-1 text-primary underline underline-offset-4"
      >
        {t.docs}
      </a>
    </section>
  )
}
