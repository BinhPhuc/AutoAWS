import { useState } from 'react'
import { CheckCircle2, KeyRound, ShieldAlert, XCircle } from 'lucide-react'
import { ApiError } from '@/api/client'
import type {
  BedrockAuth,
  LlmConfig,
  LlmConfigInput,
  LlmProviderName,
  LlmSecret,
  LlmSecretKey,
} from '@/api/types'
import { RegionSelect } from '@/components/connections/RegionSelect'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import { Panel } from '@/components/layout/Panel'
import { EmptyState, PageError, PageLoading } from '@/components/layout/PageState'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatusTag } from '@/components/ui/status-tag'
import { useMe } from '@/hooks/useAuth'
import { useLlmConfig, useResetLlmConfig, useSaveLlmConfig, useTestLlm } from '@/hooks/useAdmin'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'

const PROVIDERS: LlmProviderName[] = ['bedrock', 'anthropic', 'openai', 'mock']
const AUTHS: BedrockAuth[] = ['iam', 'api_key', 'access_key', 'assume_role']

/** Admin page (§10): which LLM answers and with which keys. */
export function AdminPage() {
  const t = S.admin
  const me = useMe()
  const config = useLlmConfig(!!me.data?.is_admin)

  if (me.isPending) return <PageLoading />
  if (!me.data?.is_admin)
    return (
      <PageBody>
        <EmptyState
          icon={<ShieldAlert className="size-8" />}
          title={t.onlyAdmins}
          body={t.onlyAdminsHint}
        />
      </PageBody>
    )
  return (
    <PageBody>
      <PageHeader title={t.title} description={t.subtitle} />
      {config.isPending ? (
        <PageLoading />
      ) : config.isError ? (
        <PageError error={config.error} onRetry={() => void config.refetch()} />
      ) : (
        // Re-mounted when the server's copy changes: the form starts from it
        <LlmForm key={config.data.updated_at ?? config.data.source} config={config.data} />
      )}
    </PageBody>
  )
}

function toInput(c: LlmConfig): LlmConfigInput {
  const { secrets: _b, ...bedrock } = c.bedrock
  return {
    provider: c.provider,
    bedrock,
    anthropic: { model: c.anthropic.model, base_url: c.anthropic.base_url },
    openai: { model: c.openai.model, base_url: c.openai.base_url },
    secrets: {},
  }
}

function LlmForm({ config }: { config: LlmConfig }) {
  const t = S.admin
  const save = useSaveLlmConfig()
  const reset = useResetLlmConfig()
  const test = useTestLlm()
  const [form, setForm] = useState<LlmConfigInput>(() => toInput(config))
  const [confirmReset, setConfirmReset] = useState(false)
  const dirty = JSON.stringify(form) !== JSON.stringify(toInput(config))
  const serverError =
    save.error instanceof ApiError ? save.error.message : save.error ? String(save.error) : null

  const set = <K extends 'bedrock' | 'anthropic' | 'openai'>(
    section: K,
    patch: Partial<LlmConfigInput[K]>,
  ) => setForm((f) => ({ ...f, [section]: { ...f[section], ...patch } }))
  const setSecret = (key: LlmSecretKey, value: string | null | undefined) =>
    setForm((f) => {
      const secrets = { ...f.secrets }
      if (value === undefined || value === '') delete secrets[key]
      else secrets[key] = value
      return { ...f, secrets }
    })

  const secretField = (key: LlmSecretKey, label: string, current: LlmSecret) => (
    <SecretField
      id={`secret-${key}`}
      label={label}
      current={current}
      value={form.secrets[key]}
      onChange={(v) => setSecret(key, v)}
    />
  )

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    test.reset()
    save.mutate(form)
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Panel
        title={t.provider}
        extra={
          <>
            <StatusTag tone={config.source === 'admin' ? 'info' : 'neutral'}>
              {config.source === 'admin' ? t.sourceAdmin : t.sourceEnv}
            </StatusTag>
            <StatusTag tone="neutral">
              <KeyRound aria-hidden />
              {t.storedIn}: {t.storage[config.storage] ?? config.storage}
            </StatusTag>
          </>
        }
      >
        <div className="max-w-xl space-y-1.5">
          <Label htmlFor="llm-provider">{t.provider}</Label>
          <Select
            value={form.provider}
            onValueChange={(v) => v && setForm((f) => ({ ...f, provider: v as LlmProviderName }))}
          >
            <SelectTrigger id="llm-provider" className="w-full">
              <SelectValue>{t.providers[form.provider]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map((p) => (
                <SelectItem key={p} value={p}>
                  {t.providers[p]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {config.updated_at && (
            <p className="text-xs text-muted-foreground">
              {t.lastChange(formatTime(config.updated_at), config.updated_by)}
            </p>
          )}
        </div>
      </Panel>

      {form.provider === 'bedrock' && (
        <Panel title={t.providers.bedrock}>
          <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
            <Field id="bedrock-model" label={t.model}>
              <Input
                id="bedrock-model"
                value={form.bedrock.model}
                onChange={(e) => set('bedrock', { model: e.target.value })}
                placeholder="anthropic.claude-opus-5-5"
                className="font-mono text-xs"
              />
            </Field>
            <Field id="bedrock-region" label={t.region}>
              <RegionSelect
                id="bedrock-region"
                value={form.bedrock.region}
                onChange={(region) => set('bedrock', { region })}
              />
            </Field>
            <Field id="bedrock-fallback" label={t.fallbackModel} hint={t.fallbackHint}>
              <Input
                id="bedrock-fallback"
                value={form.bedrock.fallback_model}
                onChange={(e) => set('bedrock', { fallback_model: e.target.value })}
                className="font-mono text-xs"
              />
            </Field>
            <Field id="bedrock-auth" label={t.auth} hint={t.authHints[form.bedrock.auth]}>
              <Select
                value={form.bedrock.auth}
                onValueChange={(v) => v && set('bedrock', { auth: v as BedrockAuth })}
              >
                <SelectTrigger id="bedrock-auth" className="w-full">
                  <SelectValue>{t.auths[form.bedrock.auth]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {AUTHS.map((a) => (
                    <SelectItem key={a} value={a}>
                      {t.auths[a]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            {form.bedrock.auth === 'api_key' &&
              secretField('bedrock.api_key', t.bedrockApiKey, config.bedrock.secrets.api_key)}
            {form.bedrock.auth === 'access_key' && (
              <>
                <Field id="bedrock-key-id" label={t.accessKeyId}>
                  <Input
                    id="bedrock-key-id"
                    value={form.bedrock.access_key_id}
                    onChange={(e) => set('bedrock', { access_key_id: e.target.value.trim() })}
                    placeholder="AKIA…"
                    className="font-mono text-xs"
                    autoComplete="off"
                  />
                </Field>
                {secretField(
                  'bedrock.secret_access_key',
                  t.secretAccessKey,
                  config.bedrock.secrets.secret_access_key,
                )}
              </>
            )}
            {form.bedrock.auth === 'assume_role' && (
              <>
                <Field id="bedrock-role" label={t.roleArn}>
                  <Input
                    id="bedrock-role"
                    value={form.bedrock.role_arn}
                    onChange={(e) => set('bedrock', { role_arn: e.target.value.trim() })}
                    placeholder="arn:aws:iam::123456789012:role/AutoAWSBedrockInvoke"
                    className="font-mono text-xs"
                  />
                </Field>
                <Field id="bedrock-ext" label={t.externalId}>
                  <Input
                    id="bedrock-ext"
                    value={form.bedrock.external_id}
                    onChange={(e) => set('bedrock', { external_id: e.target.value.trim() })}
                    className="font-mono text-xs"
                  />
                </Field>
              </>
            )}
          </div>
        </Panel>
      )}

      {form.provider === 'anthropic' && (
        <Panel title={t.providers.anthropic}>
          <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
            <Field id="anthropic-model" label={t.model}>
              <Input
                id="anthropic-model"
                value={form.anthropic.model}
                onChange={(e) => set('anthropic', { model: e.target.value })}
                placeholder="claude-opus-5-5"
                className="font-mono text-xs"
              />
            </Field>
            <Field id="anthropic-url" label={t.baseUrl} hint={t.anthropicBaseUrlHint}>
              <Input
                id="anthropic-url"
                value={form.anthropic.base_url}
                onChange={(e) => set('anthropic', { base_url: e.target.value.trim() })}
                placeholder="https://…"
                className="font-mono text-xs"
              />
            </Field>
            {secretField('anthropic.api_key', t.anthropicKey, config.anthropic.secrets.api_key)}
          </div>
        </Panel>
      )}

      {form.provider === 'openai' && (
        <Panel title={t.providers.openai}>
          <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
            <Field id="openai-model" label={t.model}>
              <Input
                id="openai-model"
                value={form.openai.model}
                onChange={(e) => set('openai', { model: e.target.value })}
                placeholder="qwen2.5:latest"
                className="font-mono text-xs"
              />
            </Field>
            <Field id="openai-url" label={t.baseUrl} hint={t.openaiBaseUrlHint}>
              <Input
                id="openai-url"
                value={form.openai.base_url}
                onChange={(e) => set('openai', { base_url: e.target.value.trim() })}
                className="font-mono text-xs"
              />
            </Field>
            {secretField('openai.api_key', t.openaiKey, config.openai.secrets.api_key)}
          </div>
        </Panel>
      )}

      {form.provider === 'mock' && (
        <Panel title={t.providers.mock}>
          <p className="text-muted-foreground">{t.mockHint}</p>
        </Panel>
      )}

      {serverError && (
        <p
          role="alert"
          className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger"
        >
          {serverError}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!dirty || save.isPending}>
          {save.isPending ? t.saving : t.save}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => test.mutate()}
          disabled={dirty || test.isPending}
          title={t.testHint}
        >
          {test.isPending ? t.testing : t.test}
        </Button>
        {config.source === 'admin' && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => setConfirmReset(true)}
            disabled={reset.isPending}
          >
            {t.reset}
          </Button>
        )}
        <span className="text-xs text-muted-foreground">{dirty ? t.unsaved : t.testHint}</span>
      </div>

      {test.data && (
        <p
          role="status"
          className={
            test.data.ok
              ? 'flex items-center gap-2 rounded-md border border-success-border bg-success-bg px-3 py-2 text-success'
              : 'flex items-center gap-2 rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger'
          }
        >
          {test.data.ok ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
          <span>
            <span className="font-mono">
              {test.data.provider}
              {test.data.model ? ` · ${test.data.model}` : ''}
            </span>
            {' — '}
            {test.data.ok
              ? t.testOk(test.data.latency_ms, test.data.reply)
              : `${t.testFailed}: ${test.data.error}`}
          </span>
        </p>
      )}

      <Dialog open={confirmReset} onOpenChange={setConfirmReset}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.resetTitle}</DialogTitle>
            <DialogDescription>{t.resetBody}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmReset(false)}>
              {S.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => reset.mutate(undefined, { onSettled: () => setConfirmReset(false) })}
              disabled={reset.isPending}
            >
              {t.reset}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  )
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

/** Write-only key input: shows whether a key is stored (and its last 4 characters), never
 * the key itself. `value`: undefined = keep, string = replace, null = remove. */
function SecretField({
  id,
  label,
  current,
  value,
  onChange,
}: {
  id: string
  label: string
  current: LlmSecret
  value: string | null | undefined
  onChange: (value: string | null | undefined) => void
}) {
  const t = S.admin
  const removing = value === null
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input
          id={id}
          type="password"
          autoComplete="new-password"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || undefined)}
          placeholder={current.set ? t.secretPlaceholderReplace : t.secretPlaceholderNew}
          disabled={removing}
          className="font-mono text-xs"
          aria-describedby={`${id}-state`}
        />
        {current.set && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => onChange(removing ? undefined : null)}
          >
            {removing ? t.secretUndo : t.secretRemove}
          </Button>
        )}
      </div>
      <p id={`${id}-state`} className="text-xs text-muted-foreground">
        {removing
          ? t.secretWillRemove
          : current.set
            ? `${t.secretSet(current.hint)}${current.updated_at ? ` · ${t.secretUpdated(formatTime(current.updated_at))}` : ''}`
            : t.secretNotSet}
      </p>
    </div>
  )
}
