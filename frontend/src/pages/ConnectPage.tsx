import { useState } from 'react'
import { Plug, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ConnectionForm } from '@/components/connections/ConnectionForm'
import { ConnectionsTable } from '@/components/connections/ConnectionsTable'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import { Panel } from '@/components/layout/Panel'
import { EmptyState, PageError } from '@/components/layout/PageState'
import { useConnections } from '@/hooks/useConnections'
import { S } from '@/lib/strings'

export function ConnectPage() {
  const { data, isPending, isError, error, refetch } = useConnections()
  const [open, setOpen] = useState(false)
  const t = S.connections
  const add = (
    <Button onClick={() => setOpen(true)}>
      <Plus />
      {t.add}
    </Button>
  )

  return (
    <PageBody>
      <PageHeader title={t.title} description={t.subtitle} actions={add} />

      <Panel
        title={t.listTitle}
        extra={
          data && (
            <span className="tabular text-xs text-muted-foreground">{t.count(data.length)}</span>
          )
        }
        flush
      >
        {isPending ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : isError ? (
          <PageError error={error} onRetry={() => void refetch()} />
        ) : data.length === 0 ? (
          <EmptyState
            icon={<Plug className="size-8" />}
            title={t.empty}
            body={t.emptyHint}
            action={add}
          />
        ) : (
          <ConnectionsTable connections={data} />
        )}
      </Panel>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t.form.title}</DialogTitle>
            <DialogDescription>{t.form.description}</DialogDescription>
          </DialogHeader>
          <ConnectionForm onCreated={() => setOpen(false)} />
        </DialogContent>
      </Dialog>
    </PageBody>
  )
}
