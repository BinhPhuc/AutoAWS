import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Connection, CreateRoleConnection } from '@/api/types'
import { useCreateConnection, useVerifyConnection } from '@/hooks/useConnections'
import { DEFAULT_REGION, generateExternalId } from '@/lib/format'
import { S } from '@/lib/strings'
import { RegionSelect } from './RegionSelect'
import { RoleSetupGuide } from './RoleSetupGuide'

const ARN_RE = /^arn:aws:iam::\d{12}:role\/.+$/

interface Props {
  /** Called after the role connection has been verified successfully. */
  onCreated: (c: Connection) => void
}

export function ConnectionForm({ onCreated }: Props) {
  const t = S.connections.form
  const create = useCreateConnection()
  const verify = useVerifyConnection()

  const [name, setName] = useState('')
  const [region, setRegion] = useState(DEFAULT_REGION)
  const [roleArn, setRoleArn] = useState('')
  const [externalId, setExternalId] = useState(generateExternalId)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [created, setCreated] = useState<Connection | null>(null)

  const validate = (): CreateRoleConnection | null => {
    const e: Record<string, string> = {}
    if (!name.trim()) e.name = t.errors.nameRequired
    if (!region) e.region = t.errors.regionRequired
    if (!ARN_RE.test(roleArn.trim())) e.roleArn = t.errors.roleArnInvalid
    setErrors(e)
    if (Object.keys(e).length) return null
    return {
      type: 'role',
      name: name.trim(),
      region,
      role_arn: roleArn.trim(),
      external_id: externalId,
    }
  }

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    const input = validate()
    if (!input) return
    create.mutate(input, {
      onSuccess: ({ data }) => {
        setCreated(data)
        // Both setup methods provide an existing role before the connection is saved.
        verify.mutate(data.id, {
          onSuccess: ({ data: result }) => {
            if (result.status === 'connected') onCreated(data)
          },
        })
      },
    })
  }

  // Keep a saved role connection available for verification retries.
  if (created) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">{t.roleReady}</p>
        <code className="block break-all text-xs">{created.role_arn}</code>
        {verify.data?.data.error && (
          <p role="alert" className="text-sm text-destructive">
            {verify.data.data.error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button
            onClick={() =>
              verify.mutate(created.id, {
                onSuccess: ({ data: result }) => {
                  if (result.status === 'connected') onCreated(created)
                },
              })
            }
            disabled={verify.isPending}
          >
            {verify.isPending ? S.connections.verifying : S.connections.verify}
          </Button>
        </div>
      </div>
    )
  }

  const busy = create.isPending || verify.isPending

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-muted-foreground">{t.roleOnlyHint}</p>
      <RoleSetupGuide externalId={externalId} />
      <div className="mt-3 space-y-3">
        <Field label={t.name} error={errors.name} htmlFor="conn-name">
          <Input
            id="conn-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t.namePlaceholder}
            autoFocus
          />
        </Field>
        <Field label={t.region} error={errors.region} htmlFor="conn-region">
          <RegionSelect id="conn-region" value={region} onChange={setRegion} />
        </Field>
      </div>

      <div className="space-y-3 pt-1">
        <Field label={t.roleArn} error={errors.roleArn} htmlFor="conn-arn">
          <Input
            id="conn-arn"
            value={roleArn}
            onChange={(e) => setRoleArn(e.target.value)}
            placeholder={t.roleArnPlaceholder}
            className="font-mono text-xs"
          />
        </Field>
        <Field label={t.externalId} hint={t.externalIdHint} htmlFor="conn-extid">
          <div className="flex gap-2">
            <Input
              id="conn-extid"
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              className="font-mono text-xs"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={t.regenerate}
              onClick={() => setExternalId(generateExternalId())}
            >
              <RefreshCw />
            </Button>
          </div>
        </Field>
      </div>

      <div className="flex justify-end">
        <Button type="submit" disabled={busy}>
          {busy ? t.submitting : t.submitRole}
        </Button>
      </div>
    </form>
  )
}

function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label: string
  hint?: string
  error?: string
  htmlFor: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}
