import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronRight, MessageSquare, RefreshCw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { StatusTag } from '@/components/ui/status-tag'
import { Mono, TBody, THead, Table, Td, Th, Tr } from '@/components/ui/table'
import type { Connection } from '@/api/types'
import { DescriptionList } from '@/components/layout/Panel'
import { StatusBadge } from '@/components/layout/ConnectionBadge'
import { useActiveConnection } from '@/hooks/useActiveConnection'
import { useDeleteConnection, useVerifyConnection } from '@/hooks/useConnections'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'
import { CloudFormationSnippet } from './CloudFormationSnippet'

export function ConnectionsTable({ connections }: { connections: Connection[] }) {
  const t = S.connections
  return (
    <Table>
      <THead>
        <Tr>
          <Th className="w-8">
            <span className="sr-only">{t.details}</span>
          </Th>
          <Th>{t.colName}</Th>
          <Th>{t.colStatus}</Th>
          <Th>{t.colType}</Th>
          <Th>{t.colAccount}</Th>
          <Th>{t.colRegion}</Th>
          <Th>{t.colVerified}</Th>
          <Th className="text-right">{t.colActions}</Th>
        </Tr>
      </THead>
      <TBody>
        {connections.map((c) => (
          <ConnectionRow key={c.id} connection={c} />
        ))}
      </TBody>
    </Table>
  )
}

function ConnectionRow({ connection: c }: { connection: Connection }) {
  const navigate = useNavigate()
  const verify = useVerifyConnection()
  const remove = useDeleteConnection()
  const { setActiveConnectionId } = useActiveConnection(undefined)
  const [expanded, setExpanded] = useState(c.status === 'failed')
  const [confirm, setConfirm] = useState(false)
  const t = S.connections

  return (
    <Fragment>
      <Tr>
        <Td>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-expanded={expanded}
            aria-label={`${t.details}: ${c.name}`}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </Td>
        <Td className="font-medium">{c.name}</Td>
        <Td>
          <StatusBadge status={c.status} />
        </Td>
        <Td>
          <StatusTag tone={c.type === 'role' ? 'info' : 'neutral'}>
            {c.type === 'role' ? t.typeRole : t.typeAccessKey}
          </StatusTag>
        </Td>
        <Td>
          <Mono className="tabular">{c.account_id ?? '—'}</Mono>
        </Td>
        <Td>
          <Mono>{c.region}</Mono>
        </Td>
        <Td className="tabular whitespace-nowrap text-muted-foreground">
          {c.last_verified_at ? formatTime(c.last_verified_at) : t.never}
        </Td>
        <Td>
          <div className="flex justify-end gap-1.5">
            <Button
              variant="outline"
              size="sm"
              onClick={() => verify.mutate(c.id)}
              disabled={verify.isPending}
            >
              <RefreshCw className={verify.isPending ? 'animate-spin' : undefined} />
              {verify.isPending ? t.verifying : t.verify}
            </Button>
            {c.status === 'connected' && (
              <Button
                size="sm"
                onClick={() => {
                  setActiveConnectionId(c.id)
                  navigate('/chat')
                }}
              >
                <MessageSquare />
                {t.startChat}
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`${S.common.delete}: ${c.name}`}
              onClick={() => setConfirm(true)}
              disabled={remove.isPending}
              className="text-danger hover:bg-danger-bg hover:text-danger"
            >
              <Trash2 />
            </Button>
          </div>
        </Td>
      </Tr>
      {expanded && (
        <tr className="border-b bg-muted/40">
          <td />
          <td colSpan={7} className="space-y-3 px-3 py-3">
            <DescriptionList
              items={[
                { label: 'ID', value: <Mono>{c.id}</Mono> },
                ...(c.role_arn ? [{ label: 'Role ARN', value: <Mono>{c.role_arn}</Mono> }] : []),
                ...(c.external_id
                  ? [{ label: 'External ID', value: <Mono>{c.external_id}</Mono> }]
                  : []),
                ...(c.access_key_id_masked
                  ? [{ label: t.colCredential, value: <Mono>{c.access_key_id_masked}</Mono> }]
                  : []),
                {
                  label: S.common.created,
                  value: <span className="tabular">{formatTime(c.created_at)}</span>,
                },
              ]}
            />
            {c.last_error && c.status === 'failed' && (
              <p
                role="alert"
                className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger"
              >
                {c.last_error}
              </p>
            )}
            {c.type === 'role' && <CloudFormationSnippet connectionId={c.id} />}
          </td>
        </tr>
      )}

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.deleteConfirmTitle}</DialogTitle>
            <DialogDescription>{t.deleteConfirmBody}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              {S.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => remove.mutate(c.id, { onSettled: () => setConfirm(false) })}
              disabled={remove.isPending}
            >
              {S.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Fragment>
  )
}
