import { useState } from 'react'
import { ChevronRight, CircleAlert, CircleCheck, Loader2 } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ToolCall } from '@/api/types'
import { useToolLookup } from '@/hooks/useTools'
import { iconForGroup } from '@/lib/toolIcons'
import { S } from '@/lib/strings'
import { cn } from '@/lib/utils'

export function ToolCallTimeline({
  toolCalls,
  streaming = false,
  defaultOpen = false,
}: {
  toolCalls: ToolCall[]
  streaming?: boolean
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const lookup = useToolLookup()
  if (toolCalls.length === 0) return null

  const total = toolCalls.reduce((s, tc) => s + (tc.duration_ms || 0), 0)
  const t = S.timeline

  return (
    <Collapsible open={open || streaming} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs text-muted-foreground hover:bg-muted">
        <ChevronRight
          className={cn('size-3.5 transition-transform', (open || streaming) && 'rotate-90')}
        />
        {streaming ? t.running : t.summary(toolCalls.length, total)}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ol className="mt-1 space-y-1 border-l pl-3 ml-3">
          {toolCalls.map((tc, i) => {
            const spec = lookup(tc.tool)
            const Icon = iconForGroup(spec.group)
            const running =
              streaming && i === toolCalls.length - 1 && !tc.output_summary && tc.status === 'ok'
            return (
              <li key={tc.id} className="rounded-md px-2 py-1 text-xs">
                <div className="flex items-center gap-1.5">
                  <Icon className="size-3.5 text-muted-foreground" />
                  <span className="font-medium">{spec.label}</span>
                  <code className="text-[10px] text-muted-foreground">{tc.tool}</code>
                  <span className="ml-auto flex items-center gap-1 text-muted-foreground">
                    {running ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : tc.status === 'error' ? (
                      <CircleAlert className="size-3.5 text-destructive" />
                    ) : (
                      <CircleCheck className="size-3.5 text-emerald-600" />
                    )}
                    {tc.duration_ms > 0 && <span>{tc.duration_ms} ms</span>}
                  </span>
                </div>
                {Object.keys(tc.input ?? {}).length > 0 && (
                  <div className="mt-0.5 text-muted-foreground">
                    <span className="mr-1">{t.input}:</span>
                    <code className="break-all">{JSON.stringify(tc.input)}</code>
                  </div>
                )}
                {tc.output_summary && (
                  <div
                    className={cn(
                      'mt-0.5',
                      tc.status === 'error' ? 'text-destructive' : 'text-foreground/80',
                    )}
                  >
                    <span className="mr-1 text-muted-foreground">
                      {tc.status === 'error' ? t.error : t.output}:
                    </span>
                    {tc.output_summary}
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  )
}
