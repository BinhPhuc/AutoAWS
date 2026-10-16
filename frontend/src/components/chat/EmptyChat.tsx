import { Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { S } from '@/lib/strings'

export function EmptyChat({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center gap-5 px-4 text-center">
      <Sparkles className="size-8 text-muted-foreground" />
      <div className="space-y-2">
        <h2 className="font-heading text-xl font-semibold">{S.chat.emptyTitle}</h2>
        <p className="text-sm text-muted-foreground">{S.chat.emptyBody}</p>
      </div>
      <div className="grid w-full gap-2 sm:grid-cols-1">
        {S.chat.examples.map((ex) => (
          <Button
            key={ex}
            variant="outline"
            className="h-auto justify-start whitespace-normal px-3 py-2 text-left text-sm font-normal"
            onClick={() => onPick(ex)}
          >
            {ex}
          </Button>
        ))}
      </div>
    </div>
  )
}
