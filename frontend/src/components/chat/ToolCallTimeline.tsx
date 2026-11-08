import { useState } from 'react'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import type { ToolCall } from '@/api/types'
import { Panel } from '@/components/layout/Panel'
import { StatusTag } from '@/components/ui/status-tag'
import { Mono, TBody, THead, Table, Td, Th, Tr } from '@/components/ui/table'
import { useToolLookup } from '@/hooks/useTools'
import { iconForGroup } from '@/lib/toolIcons'
import { S } from '@/lib/strings'

/** The AWS reads of one turn, as a table (tool · input · result · status · time). */
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

  const t = S.timeline
  const total = toolCalls.reduce((s, tc) => s + (tc.duration_ms || 0), 0)
  const expanded = open || streaming

  return (
    <Panel
      flush
      title={
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={expanded}
          className="flex cursor-pointer items-center gap-1.5 rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {expanded ? (
            <ChevronDown className="size-4" aria-hidden />
          ) : (
            <ChevronRight className="size-4" aria-hidden />
          )}
          {t.title}
        </button>
      }
      extra={
        <span className="tabular text-xs text-muted-foreground">
          {streaming ? t.running : t.summary(toolCalls.length, total)}
        </span>
      }
    >
      {expanded && (
        <Table>
          <THead>
            <Tr>
              <Th>{t.colTool}</Th>
              <Th>{t.colInput}</Th>
              <Th>{t.colResult}</Th>
              <Th>{t.colStatus}</Th>
              <Th className="text-right">{t.colTime}</Th>
            </Tr>
          </THead>
          <TBody>
            {toolCalls.map((tc, i) => {
              const spec = lookup(tc.tool)
              const Icon = iconForGroup(spec.group)
              const running =
                streaming && i === toolCalls.length - 1 && !tc.output_summary && tc.status === 'ok'
              const input = Object.keys(tc.input ?? {}).length ? JSON.stringify(tc.input) : '—'
              return (
                <Tr key={tc.id}>
                  <Td className="whitespace-nowrap">
                    <div className="flex items-center gap-1.5">
                      <Icon className="size-3.5 text-muted-foreground" aria-hidden />
                      <span className="font-medium">{spec.label}</span>
                    </div>
                    <Mono className="text-muted-foreground">{tc.tool}</Mono>
                  </Td>
                  <Td className="max-w-64">
                    <Mono className="line-clamp-2" title={input}>
                      {input}
                    </Mono>
                  </Td>
                  <Td className={tc.status === 'error' ? 'text-danger' : undefined}>
                    {tc.output_summary || '—'}
                  </Td>
                  <Td className="whitespace-nowrap">
                    {running ? (
                      <StatusTag tone="info">
                        <Loader2 className="animate-spin" aria-hidden />
                        {t.running}
                      </StatusTag>
                    ) : tc.status === 'error' ? (
                      <StatusTag tone="danger">{t.error}</StatusTag>
                    ) : tc.cached ? (
                      <StatusTag tone="neutral">{t.cached}</StatusTag>
                    ) : (
                      <StatusTag tone="success">{t.ok}</StatusTag>
                    )}
                  </Td>
                  <Td className="tabular text-right whitespace-nowrap text-muted-foreground">
                    {tc.duration_ms > 0 ? `${tc.duration_ms} ms` : '—'}
                  </Td>
                </Tr>
              )
            })}
          </TBody>
        </Table>
      )}
    </Panel>
  )
}
