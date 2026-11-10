import { useState } from 'react'
import { BookOpen, ShieldCheck } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { S } from '@/lib/strings'
import { CloudFormationSnippet, CopyButton } from './CloudFormationSnippet'
import { ConnectionGuide } from './ConnectionGuide'

export type RoleSetupMethod = 'manual' | 'cloudformation'

export function RoleSetupGuide({
  externalId,
  method,
  onMethodChange,
}: {
  externalId: string
  method?: RoleSetupMethod
  onMethodChange?: (method: RoleSetupMethod) => void
}) {
  const [localMethod, setLocalMethod] = useState<RoleSetupMethod>('cloudformation')
  const t = S.connections.form
  const guide = S.connections.guide
  return (
    <Tabs
      value={method ?? localMethod}
      onValueChange={(value) => (onMethodChange ?? setLocalMethod)(value as RoleSetupMethod)}
      className="min-w-0"
    >
      <TabsList className="h-auto w-full flex-wrap">
        <TabsTrigger value="cloudformation" className="min-h-10 flex-1 flex-wrap whitespace-normal">
          {t.automaticSetup}
          <Badge variant="secondary" className="ml-1">
            {t.recommended}
          </Badge>
        </TabsTrigger>
        <TabsTrigger value="manual" className="min-h-10 flex-1 whitespace-normal">
          {t.manualSetup}
        </TabsTrigger>
      </TabsList>
      <TabsContent value="manual" className="min-w-0 pt-3">
        <section className="space-y-4 rounded-md border bg-primary/5 p-4">
          <h3 className="flex items-center gap-2 font-semibold">
            <ShieldCheck aria-hidden="true" className="size-4" />
            {t.manualTitle}
          </h3>
          <p className="text-sm text-muted-foreground">{t.manualHint}</p>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-background p-3">
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">{guide.roleNameLabel}</span>
                <Badge variant="outline">{guide.requiredExact}</Badge>
              </div>
              <code className="block break-all font-semibold">{guide.roleName}</code>
            </div>
            <CopyButton
              text={guide.roleName}
              accessibleLabel={`${S.common.copy}: ${guide.roleNameLabel}`}
            />
          </div>
          <Dialog>
            <DialogTrigger
              render={
                <Button
                  type="button"
                  variant="outline"
                  className="h-auto min-h-10 whitespace-normal text-left"
                />
              }
            >
              <BookOpen aria-hidden="true" />
              {t.roleHelpButton}
            </DialogTrigger>
            <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-4xl">
              <DialogHeader className="pr-8">
                <DialogTitle>{guide.roleTitle}</DialogTitle>
                <DialogDescription>{t.manualHelpDescription}</DialogDescription>
              </DialogHeader>
              <ConnectionGuide externalId={externalId} />
            </DialogContent>
          </Dialog>
          <p className="text-xs text-muted-foreground">{t.roleArnReadyHint}</p>
        </section>
      </TabsContent>
      <TabsContent
        value="cloudformation"
        className="min-w-0 space-y-3 rounded-md border bg-background p-4 mt-3"
      >
        <p className="text-sm text-muted-foreground">{t.automaticHint}</p>
        <CloudFormationSnippet externalId={externalId} />
      </TabsContent>
    </Tabs>
  )
}
