import { useConnectionSetup } from '@/hooks/useConnections'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useTools } from '@/hooks/useTools'
import { S } from '@/lib/strings'
import { InstructionText } from './InstructionText'
import { CopyButton } from './CloudFormationSnippet'

const json = (value: unknown) => JSON.stringify(value, null, 2)

export function ConnectionGuide({ externalId }: { externalId: string }) {
  const t = S.connections.guide
  const { data: tools, isPending, isError } = useTools()
  const setup = useConnectionSetup()
  const accountId = setup.data?.account_id
  const setupReady = !!accountId && /^[0-9]{12}$/.test(accountId)
  const actions = [...new Set(tools?.flatMap((tool) => tool.aws_actions) ?? [])]
  const readPolicy = json({
    Version: '2012-10-17',
    Statement: [
      {
        Sid: 'AllowReadOnlyDiagnostics',
        Effect: 'Allow',
        Resource: '*',
        Action: [...new Set([...actions, 'sts:GetCallerIdentity', 'ec2:DescribeRegions'])].sort(),
      },
      {
        Sid: 'DenyBusinessData',
        Effect: 'Deny',
        Resource: '*',
        Action: [
          's3:GetObject*',
          'secretsmanager:GetSecretValue',
          'ssm:GetParameter*',
          'kms:Decrypt',
          'dynamodb:GetItem',
          'dynamodb:Query',
          'dynamodb:Scan',
          'rds-data:*',
        ],
      },
    ],
  })
  const trustPolicy = json({
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Principal: { AWS: `arn:aws:iam::${accountId}:root` },
        Action: 'sts:AssumeRole',
        Condition: { StringEquals: { 'sts:ExternalId': externalId } },
      },
    ],
  })

  return (
    <section className="min-w-0 space-y-3 rounded-lg border bg-muted/30 p-4 text-sm">
      <h3 className="font-medium">{t.roleTitle}</h3>
      <>
        <p className="leading-relaxed text-muted-foreground">{t.roleIntro}</p>
        <ol className="list-none space-y-4">
          {t.roleSteps.map((step, index) => (
            <li key={step.id} className="min-w-0 space-y-3 rounded-xl border bg-background p-4">
              <h4 className="flex items-center gap-3 font-semibold text-foreground">
                <span
                  aria-hidden="true"
                  className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary"
                >
                  {index + 1}
                </span>
                {step.title}
              </h4>
              <p className="leading-relaxed text-muted-foreground">
                <InstructionText text={step.body} />
              </p>
              {step.id === 'trust' && (
                <KeyValue
                  label={t.connectionExternalId}
                  value={externalId}
                  badge={t.keepUnchanged}
                  hint={t.externalIdNote}
                  caution
                />
              )}
              {step.id === 'name' && (
                <div className="space-y-3">
                  <KeyValue
                    label={t.roleNameLabel}
                    value={t.roleName}
                    badge={t.requiredExact}
                    hint={t.roleNameHint}
                  />
                  <KeyValue
                    label={t.policyNameLabel}
                    value={t.policyName}
                    badge={t.suggested}
                    hint={t.policyNameHint}
                  />
                  <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
                    <p className="font-semibold">{t.finalReviewTitle}</p>
                    <ul className="list-disc space-y-2 pl-5 text-muted-foreground">
                      {t.finalReviewItems.map((item) => (
                        <li key={item}>
                          <InstructionText text={item} />
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              {step.id === 'trust' &&
                (setup.isPending ? (
                  <p role="status">{S.common.loading}</p>
                ) : setup.isError || !setupReady ? (
                  <div className="space-y-2">
                    <p role="alert" className="text-destructive">
                      {t.setupUnavailable}
                    </p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={setup.isFetching}
                      onClick={() => void setup.refetch()}
                    >
                      {setup.isFetching ? S.common.loading : S.common.retry}
                    </Button>
                  </div>
                ) : (
                  <Policy title={t.trustTitle} hint={t.trustHint} code={trustPolicy} />
                ))}
              {step.id === 'read' && (
                <PermissionsPolicy
                  actions={actions}
                  policy={readPolicy}
                  isPending={isPending}
                  isError={isError}
                />
              )}
              {'after' in step && (
                <p className="leading-relaxed text-muted-foreground">
                  <InstructionText text={step.after} />
                </p>
              )}
            </li>
          ))}
        </ol>
        <p className="text-xs leading-relaxed text-muted-foreground">{t.existingRoleHint}</p>
        <details className="min-w-0 rounded-md border bg-background p-3">
          <summary className="cursor-pointer rounded-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">
            {t.cliTitle}
          </summary>
          <div className="mt-3">
            <Policy
              title={t.cliTitle}
              hint={t.cliHint}
              code={'aws iam get-role --role-name AutoAWSReadOnly --query Role.Arn --output text'}
            />
          </div>
        </details>
      </>
      <p className="text-xs text-muted-foreground">{t.revokeAccessNote}</p>
      <a
        className="inline-block py-1 text-primary underline underline-offset-4"
        target="_blank"
        rel="noreferrer"
        href="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-custom.html"
      >
        {t.docsRole}
      </a>
    </section>
  )
}

function Policy({ title, hint, code }: { title: string; hint: string; code: string }) {
  return (
    <div className="min-w-0 space-y-2">
      <h4 className="font-medium">{title}</h4>
      <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      <pre
        tabIndex={0}
        aria-label={title}
        className="max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed focus-visible:outline-2 focus-visible:outline-ring"
      >
        <code>{code}</code>
      </pre>
      <CopyButton text={code} accessibleLabel={`${S.common.copy}: ${title}`} />
    </div>
  )
}

function PermissionsPolicy({
  actions,
  policy,
  isPending,
  isError,
}: {
  actions: string[]
  policy: string
  isPending: boolean
  isError: boolean
}) {
  const t = S.connections.guide
  if (isPending) return <p role="status">{S.common.loading}</p>
  if (isError)
    return (
      <p role="alert" className="text-destructive">
        {t.readError}
      </p>
    )
  if (actions.length === 0) return <p>{t.noTools}</p>
  return <Policy title={t.readTitle} hint={t.readHint} code={policy} />
}

function KeyValue({
  label,
  value,
  badge,
  hint,
  caution = false,
}: {
  label: string
  value: string
  badge: string
  hint: string
  caution?: boolean
}) {
  return (
    <div
      className={
        caution
          ? 'space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100'
          : 'space-y-3 rounded-lg border border-primary/20 bg-primary/5 p-3'
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{label}</span>
        <Badge
          variant="outline"
          className={
            caution ? 'border-amber-500/40 text-inherit' : 'border-primary/30 text-primary'
          }
        >
          {badge}
        </Badge>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <code className="min-w-0 break-all font-mono text-base font-semibold">{value}</code>
        <CopyButton text={value} accessibleLabel={`${S.common.copy}: ${label}`} />
      </div>
      <p className="text-xs leading-relaxed">{hint}</p>
    </div>
  )
}
