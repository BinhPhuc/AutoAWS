import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useCloudFormation } from '@/hooks/useConnections'
import { S } from '@/lib/strings'

export function CopyButton({ text, label = S.common.copy }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      {copied ? <Check /> : <Copy />}
      {copied ? S.common.copied : label}
    </Button>
  )
}

export function CloudFormationSnippet({ connectionId }: { connectionId: string }) {
  const { data, isPending, isError } = useCloudFormation(connectionId)
  const t = S.connections.cfn

  if (isPending)
    return (
      <div className="space-y-2">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-32" />
      </div>
    )
  if (isError) return <p className="text-sm text-destructive">{t.loadError}</p>

  return (
    <div className="space-y-3 text-sm">
      <h4 className="font-medium">{t.title}</h4>
      <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
        <li>{t.step1}</li>
        <li>{t.step2}</li>
        <li>{t.step3}</li>
      </ol>
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <span className="text-muted-foreground">{t.stackName}</span>
        <code>{data.stack_name}</code>
        <span className="text-muted-foreground">{t.externalId}</span>
        <code className="break-all">{data.external_id}</code>
      </div>
      <div className="relative">
        <pre className="max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
          {data.template_yaml}
        </pre>
        <div className="absolute top-2 right-2">
          <CopyButton text={data.template_yaml} label={t.copyTemplate} />
        </div>
      </div>
    </div>
  )
}
