import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { KeyRound, MessageSquare, ShieldCheck, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { Connection } from '@/api/types'
import { useDeleteConnection, useVerifyConnection } from '@/hooks/useConnections'
import { useActiveConnection } from '@/hooks/useActiveConnection'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'
import { StatusBadge } from '@/components/layout/ConnectionBadge'
import { CloudFormationSnippet } from './CloudFormationSnippet'

export function ConnectionCard({ connection: c }: { connection: Connection }) {
  const navigate = useNavigate()
  const verify = useVerifyConnection()
  const remove = useDeleteConnection()
  const { setActiveConnectionId } = useActiveConnection(undefined)
  const [confirm, setConfirm] = useState(false)
  const [showCfn, setShowCfn] = useState(false)
  const t = S.connections

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <span className="truncate">{c.name}</span>
            <StatusBadge status={c.status} />
          </CardTitle>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Badge variant="outline">
              {c.type === 'role' ? <ShieldCheck /> : <KeyRound />}
              {c.type === 'role' ? t.typeRole : t.typeAccessKey}
            </Badge>
            <span>{c.region}</span>
            {c.account_id && (
              <span>
                · {t.account} {c.account_id}
              </span>
            )}
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={S.common.delete}
          onClick={() => setConfirm(true)}
          disabled={remove.isPending}
        >
          <Trash2 />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {c.role_arn && (
            <>
              <dt className="text-muted-foreground">ARN</dt>
              <dd className="truncate font-mono">{c.role_arn}</dd>
            </>
          )}
          {c.access_key_id_masked && (
            <>
              <dt className="text-muted-foreground">Key</dt>
              <dd className="font-mono">{c.access_key_id_masked}</dd>
            </>
          )}
          <dt className="text-muted-foreground">{t.lastVerified}</dt>
          <dd>{c.last_verified_at ? formatTime(c.last_verified_at) : t.never}</dd>
        </dl>
        {c.last_error && c.status === 'failed' && (
          <p className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">
            {c.last_error}
          </p>
        )}
        {showCfn && c.type === 'role' && <CloudFormationSnippet connectionId={c.id} />}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => verify.mutate(c.id)}
            disabled={verify.isPending}
          >
            {verify.isPending ? t.verifying : t.verify}
          </Button>
          {c.type === 'role' && (
            <Button variant="ghost" size="sm" onClick={() => setShowCfn((v) => !v)}>
              {t.cfn.title}
            </Button>
          )}
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
        </div>
      </CardContent>

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
    </Card>
  )
}
