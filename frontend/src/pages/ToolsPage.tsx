import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import { Panel } from '@/components/layout/Panel'
import { PageError, PageLoading } from '@/components/layout/PageState'
import { StatusTag } from '@/components/ui/status-tag'
import { Mono, TBody, THead, Table, Td, Th, Tr } from '@/components/ui/table'
import type { ToolSpec } from '@/api/types'
import { useTools } from '@/hooks/useTools'
import { iconForGroup } from '@/lib/toolIcons'
import { S } from '@/lib/strings'

/** Catalogue of the read tools (GET /api/tools), grouped like the diagnosis path. */
export function ToolsPage() {
  const tools = useTools()
  const t = S.tools

  const groups = new Map<string, ToolSpec[]>()
  for (const spec of tools.data ?? []) {
    groups.set(spec.group, [...(groups.get(spec.group) ?? []), spec])
  }

  return (
    <PageBody>
      <PageHeader
        title={t.title}
        description={t.subtitle}
        actions={tools.data && <StatusTag tone="info">{t.count(tools.data.length)}</StatusTag>}
      />
      {tools.isPending ? (
        <PageLoading />
      ) : tools.isError ? (
        <PageError error={tools.error} onRetry={() => void tools.refetch()} />
      ) : (
        [...groups.entries()].map(([group, specs]) => {
          const Icon = iconForGroup(group)
          return (
            <Panel
              key={group}
              flush
              title={
                <span className="flex items-center gap-2">
                  <Icon className="size-4 text-muted-foreground" aria-hidden />
                  {t.groups[group] ?? group}
                </span>
              }
              extra={<span className="tabular text-xs text-muted-foreground">{specs.length}</span>}
            >
              <Table>
                <THead>
                  <Tr>
                    <Th className="w-56">{t.name}</Th>
                    <Th className="w-44">{t.label}</Th>
                    <Th>{t.description}</Th>
                    <Th className="w-72">{t.actions}</Th>
                  </Tr>
                </THead>
                <TBody>
                  {specs.map((s) => (
                    <Tr key={s.name}>
                      <Td>
                        <Mono className="font-medium">{s.name}</Mono>
                      </Td>
                      <Td>{s.label}</Td>
                      <Td className="text-muted-foreground">{s.description}</Td>
                      <Td>
                        <div className="flex flex-wrap gap-1">
                          {s.aws_actions.length ? (
                            s.aws_actions.map((a) => (
                              <StatusTag key={a} tone="neutral" className="font-mono font-normal">
                                {a}
                              </StatusTag>
                            ))
                          ) : (
                            <span className="text-muted-foreground">{t.noAws}</span>
                          )}
                        </div>
                      </Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            </Panel>
          )
        })
      )}
    </PageBody>
  )
}
