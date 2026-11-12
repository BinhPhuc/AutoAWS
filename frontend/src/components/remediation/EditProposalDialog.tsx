import { useState } from 'react'
import { ApiError } from '@/api/client'
import type { Proposal } from '@/api/types'
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
import { useRemediationActions, useReviseProposal } from '@/hooks/useProposals'
import { S } from '@/lib/strings'

/** The parts of a catalogue action's JSON Schema property the form understands. */
interface FieldSchema {
  type?: string
  enum?: string[]
  pattern?: string
  minimum?: number
  maximum?: number
  maxLength?: number
  description?: string
}

interface Field {
  name: string
  schema: FieldSchema
  required: boolean
}

function fieldsOf(inputSchema: Record<string, unknown>): Field[] {
  const props = (inputSchema.properties ?? {}) as Record<string, FieldSchema>
  const required = new Set((inputSchema.required ?? []) as string[])
  return Object.entries(props).map(([name, schema]) => ({
    name,
    schema,
    required: required.has(name),
  }))
}

/** An error message, or null when the value is acceptable (empty optional = left out). */
function check(field: Field, raw: string): string | null {
  const t = S.remediation
  const v = raw.trim()
  if (!v) return field.required ? t.fieldRequired : null
  const { type, pattern, minimum, maximum, maxLength } = field.schema
  if (type === 'integer') {
    const n = Number(v)
    if (
      !Number.isInteger(n) ||
      (minimum !== undefined && n < minimum) ||
      (maximum !== undefined && n > maximum)
    )
      return t.fieldInteger(minimum, maximum)
    return null
  }
  if (maxLength !== undefined && v.length > maxLength) return t.fieldTooLong(maxLength)
  if (pattern && !new RegExp(pattern).test(v)) return t.fieldPattern
  return null
}

function toParams(fields: Field[], values: Record<string, string>): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  for (const f of fields) {
    const v = (values[f.name] ?? '').trim()
    if (!v) continue
    params[f.name] = f.schema.type === 'integer' ? Number(v) : v
  }
  return params
}

interface Props {
  proposal: Proposal
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Edit a proposal's parameters (docs/API_CONTRACT.md §7, revise): the server re-runs the
 * schema check, pre-checks and preview, then a new proposal waits for approval. */
export function EditProposalDialog({ proposal, open, onOpenChange }: Props) {
  const t = S.remediation
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t.editTitle}</DialogTitle>
          <DialogDescription>{t.editHint}</DialogDescription>
        </DialogHeader>
        {/* Mounted only while open: the fields start from the proposal each time */}
        {open && <EditForm proposal={proposal} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function EditForm({ proposal: p, onDone }: { proposal: Proposal; onDone: () => void }) {
  const t = S.remediation
  const actions = useRemediationActions()
  const revise = useReviseProposal()
  const action = actions.data?.find((a) => a.name === p.action)
  const fields = action ? fieldsOf(action.input_schema) : []
  const [values, setValues] = useState<Record<string, string>>(() => stringify(p.params))
  const [errors, setErrors] = useState<Record<string, string>>({})

  if (actions.isPending) return <p className="text-muted-foreground">{S.common.loading}</p>
  if (!action || fields.length === 0)
    return <p className="text-muted-foreground">{t.editUnavailable}</p>

  const params = toParams(fields, values)
  const changed = JSON.stringify(params) !== JSON.stringify(toParams(fields, stringify(p.params)))
  const serverError =
    revise.error instanceof ApiError
      ? revise.error.message
      : revise.error
        ? String(revise.error)
        : null

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault()
    const e: Record<string, string> = {}
    for (const f of fields) {
      const err = check(f, values[f.name] ?? '')
      if (err) e[f.name] = err
    }
    setErrors(e)
    if (Object.keys(e).length || !changed) return
    revise.mutate({ id: p.id, params }, { onSuccess: onDone })
  }

  const id = (name: string) => `revise-${p.id}-${name}`
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <p className="font-mono text-xs text-muted-foreground">{action.label}</p>
      {fields.map((f) => (
        <div key={f.name} className="space-y-1.5">
          <Label htmlFor={id(f.name)}>
            <span className="font-mono">{f.name}</span>
            {!f.required && <span className="text-muted-foreground"> ({t.optional})</span>}
          </Label>
          {f.schema.enum ? (
            <Select
              value={values[f.name] ?? ''}
              onValueChange={(v) => setValues((s) => ({ ...s, [f.name]: String(v ?? '') }))}
            >
              <SelectTrigger id={id(f.name)} className="w-full">
                <SelectValue>{values[f.name] ?? ''}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {f.schema.enum.map((opt) => (
                  <SelectItem key={opt} value={opt}>
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              id={id(f.name)}
              value={values[f.name] ?? ''}
              inputMode={f.schema.type === 'integer' ? 'numeric' : undefined}
              onChange={(e) => setValues((s) => ({ ...s, [f.name]: e.target.value }))}
              className="font-mono text-xs"
              aria-invalid={!!errors[f.name]}
              aria-describedby={
                errors[f.name] || f.schema.description ? id(`${f.name}-hint`) : undefined
              }
            />
          )}
          {(errors[f.name] || f.schema.description) && (
            <p
              id={id(`${f.name}-hint`)}
              className={errors[f.name] ? 'text-xs text-danger' : 'text-xs text-muted-foreground'}
            >
              {errors[f.name] ?? f.schema.description}
            </p>
          )}
        </div>
      ))}
      {serverError && (
        <p
          role="alert"
          className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger"
        >
          {serverError}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          {S.common.cancel}
        </Button>
        <Button type="submit" disabled={!changed || revise.isPending}>
          {revise.isPending ? t.editSubmitting : t.editSubmit}
        </Button>
      </DialogFooter>
    </form>
  )
}

function stringify(params: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, v === null || v === undefined ? '' : String(v)]),
  )
}
