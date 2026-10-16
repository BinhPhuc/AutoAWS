import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Connection, ConnectionType, CreateConnectionInput } from '@/api/types'
import { useCreateConnection, useVerifyConnection } from '@/hooks/useConnections'
import { DEFAULT_REGION, generateExternalId } from '@/lib/format'
import { S } from '@/lib/strings'
import { RegionSelect } from './RegionSelect'
import { CloudFormationSnippet } from './CloudFormationSnippet'

const ARN_RE = /^arn:aws:iam::\d{12}:role\/.+$/
const AKID_RE = /^AKIA[0-9A-Z]{16}$/

interface Props {
  /** Called after the connection is created (and verify attempted for access keys). */
  onCreated: (c: Connection) => void
}

export function ConnectionForm({ onCreated }: Props) {
  const t = S.connections.form
  const create = useCreateConnection()
  const verify = useVerifyConnection()

  const [type, setType] = useState<ConnectionType>('role')
  const [name, setName] = useState('')
  const [region, setRegion] = useState(DEFAULT_REGION)
  const [accessKeyId, setAccessKeyId] = useState('')
  const [secret, setSecret] = useState('')
  const [roleArn, setRoleArn] = useState('')
  const [externalId, setExternalId] = useState(generateExternalId)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [created, setCreated] = useState<Connection | null>(null)

  const validate = (): CreateConnectionInput | null => {
    const e: Record<string, string> = {}
    if (!name.trim()) e.name = t.errors.nameRequired
    if (!region) e.region = t.errors.regionRequired
    if (type === 'access_key') {
      if (!AKID_RE.test(accessKeyId.trim())) e.accessKeyId = t.errors.accessKeyIdInvalid
      if (!secret.trim()) e.secret = t.errors.secretRequired
    } else if (!ARN_RE.test(roleArn.trim())) {
      e.roleArn = t.errors.roleArnInvalid
    }
    setErrors(e)
    if (Object.keys(e).length) return null
    return type === 'access_key'
      ? {
          type,
          name: name.trim(),
          region,
          access_key_id: accessKeyId.trim(),
          secret_access_key: secret,
        }
      : { type, name: name.trim(), region, role_arn: roleArn.trim(), external_id: externalId }
  }

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    const input = validate()
    if (!input) return
    create.mutate(input, {
      onSuccess: ({ data }) => {
        setCreated(data)
        // Access keys can be verified immediately; a role needs the CloudFormation stack first,
        // so the form switches to the CloudFormation step and verifies on demand.
        if (data.type === 'access_key') {
          verify.mutate(data.id, { onSettled: () => onCreated(data) })
        }
      },
    })
  }

  // After a role connection is created, show the CloudFormation instructions + verify button.
  if (created && created.type === 'role') {
    return (
      <div className="space-y-4">
        <CloudFormationSnippet connectionId={created.id} />
        <div className="flex justify-end gap-2">
          <Button
            onClick={() => verify.mutate(created.id, { onSuccess: () => onCreated(created) })}
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
      <Tabs value={type} onValueChange={(v) => setType(v as ConnectionType)}>
        <TabsList className="w-full">
          <TabsTrigger value="role" className="flex-1">
            {t.tabRole}
            <Badge variant="secondary" className="ml-1">
              {t.recommended}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="access_key" className="flex-1">
            {t.tabAccessKey}
          </TabsTrigger>
        </TabsList>

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

        <TabsContent value="role" className="space-y-3 pt-1">
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
        </TabsContent>

        <TabsContent value="access_key" className="space-y-3 pt-1">
          <p className="text-xs text-amber-700 dark:text-amber-300">{t.accessKeyNote}</p>
          <Field label={t.accessKeyId} error={errors.accessKeyId} htmlFor="conn-akid">
            <Input
              id="conn-akid"
              value={accessKeyId}
              onChange={(e) => setAccessKeyId(e.target.value)}
              placeholder="AKIA…"
              className="font-mono text-xs"
              autoComplete="off"
            />
          </Field>
          <Field label={t.secretAccessKey} error={errors.secret} htmlFor="conn-secret">
            <Input
              id="conn-secret"
              type="password"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              className="font-mono text-xs"
              autoComplete="new-password"
            />
          </Field>
        </TabsContent>
      </Tabs>

      <div className="flex justify-end">
        <Button type="submit" disabled={busy}>
          {busy ? t.submitting : t.submit}
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
