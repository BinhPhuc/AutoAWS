import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Connection, ConnectionPatch } from '@/api/types'
import { useUpdateConnection } from '@/hooks/useConnections'
import { S } from '@/lib/strings'
import { RegionSelect } from './RegionSelect'

const ARN_RE = /^arn:aws:iam::\d{12}:role\/.+$/

interface Props {
  connection: Connection
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Name, region and (role connections) role ARN. Type and External ID stay as they are. */
export function EditConnectionDialog({ connection, open, onOpenChange }: Props) {
  const t = S.connections.edit
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t.title}</DialogTitle>
          <DialogDescription>{t.description}</DialogDescription>
        </DialogHeader>
        {/* Mounted only while open: the fields start from the current values each time */}
        {open && <EditForm connection={connection} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function EditForm({ connection: c, onDone }: { connection: Connection; onDone: () => void }) {
  const t = S.connections.edit
  const f = S.connections.form
  const update = useUpdateConnection()
  const [name, setName] = useState(c.name)
  const [region, setRegion] = useState(c.region)
  const [roleArn, setRoleArn] = useState(c.role_arn ?? '')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const patch: ConnectionPatch = {}
  if (name.trim() !== c.name) patch.name = name.trim()
  if (region !== c.region) patch.region = region
  if (c.type === 'role' && roleArn.trim() !== (c.role_arn ?? '')) patch.role_arn = roleArn.trim()
  const changed = Object.keys(patch).length > 0
  const reverify = 'region' in patch || 'role_arn' in patch

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    const e: Record<string, string> = {}
    if (!name.trim()) e.name = f.errors.nameRequired
    if (c.type === 'role' && !ARN_RE.test(roleArn.trim())) e.roleArn = f.errors.roleArnInvalid
    setErrors(e)
    if (Object.keys(e).length || !changed) return
    update.mutate({ id: c.id, patch }, { onSuccess: onDone })
  }

  const id = (field: string) => `edit-${c.id}-${field}`
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor={id('name')}>{f.name}</Label>
        <Input
          id={id('name')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? id('name-error') : undefined}
        />
        {errors.name && (
          <p id={id('name-error')} className="text-xs text-danger">
            {errors.name}
          </p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={id('region')}>{f.region}</Label>
        <RegionSelect id={id('region')} value={region} onChange={setRegion} />
      </div>
      {c.type === 'role' && (
        <div className="space-y-1.5">
          <Label htmlFor={id('role')}>{f.roleArn}</Label>
          <Input
            id={id('role')}
            value={roleArn}
            onChange={(e) => setRoleArn(e.target.value)}
            placeholder={f.roleArnPlaceholder}
            className="font-mono text-xs"
            aria-invalid={!!errors.roleArn}
            aria-describedby={errors.roleArn ? id('role-error') : id('role-hint')}
          />
          {errors.roleArn ? (
            <p id={id('role-error')} className="text-xs text-danger">
              {errors.roleArn}
            </p>
          ) : (
            c.external_id && (
              <p id={id('role-hint')} className="text-xs break-all text-muted-foreground">
                {t.externalIdNote(c.external_id)}
              </p>
            )
          )}
        </div>
      )}
      {reverify && <p className="text-xs text-warning">{t.reverifyNote}</p>}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          {S.common.cancel}
        </Button>
        <Button type="submit" disabled={!changed || update.isPending}>
          {update.isPending ? t.saving : t.save}
        </Button>
      </DialogFooter>
    </form>
  )
}
