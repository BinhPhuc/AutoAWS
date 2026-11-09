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
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { ConnectionCard } from '@/components/connections/ConnectionCard'
import { ConnectionForm } from '@/components/connections/ConnectionForm'
import { EmptyState, PageError } from '@/components/layout/PageState'
import { useConnections } from '@/hooks/useConnections'
import { S } from '@/lib/strings'

export function ConnectPage() {
  const { data, isPending, isError, error, refetch } = useConnections()
  const [open, setOpen] = useState(false)
  const t = S.connections

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-heading text-xl font-semibold">{t.title}</h1>
            <p className="text-sm text-muted-foreground">{t.subtitle}</p>
          </div>
          <Button onClick={() => setOpen(true)}>
            <Plus />
            {t.add}
          </Button>
        </div>

        {isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-36" />
            <Skeleton className="h-36" />
          </div>
        ) : isError ? (
          <PageError error={error} onRetry={() => void refetch()} />
        ) : data.length === 0 ? (
          <EmptyState
            icon={<Plug className="size-8" />}
            title={t.empty}
            body={t.emptyHint}
            action={
              <Button onClick={() => setOpen(true)}>
                <Plus />
                {t.add}
              </Button>
            }
          />
        ) : (
          <div className="space-y-3">
            {data.map((c) => (
              <ConnectionCard key={c.id} connection={c} />
            ))}
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90dvh] overflow-hidden sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t.form.title}</DialogTitle>
            <DialogDescription>{t.form.description}</DialogDescription>
          </DialogHeader>
          <ConnectionForm onCreated={() => setOpen(false)} />
        </DialogContent>
      </Dialog>
    </ScrollArea>
  )
}
