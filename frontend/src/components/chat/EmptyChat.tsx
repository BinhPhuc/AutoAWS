import { ArrowRight, Stethoscope } from 'lucide-react'
import { Panel } from '@/components/layout/Panel'
import { S } from '@/lib/strings'

export function EmptyChat({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center gap-4 p-4 md:p-6">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
          <Stethoscope className="size-5" aria-hidden />
        </span>
        <div className="space-y-1">
          <h2 className="text-lg">{S.chat.emptyTitle}</h2>
          <p className="text-muted-foreground">{S.chat.emptyBody}</p>
        </div>
      </div>
      <Panel title={S.chat.examplesTitle} flush>
        <ul>
          {S.chat.examples.map((ex) => (
            <li key={ex} className="border-b last:border-b-0">
              <button
                type="button"
                onClick={() => onPick(ex)}
                className="group flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
              >
                <span className="flex-1">{ex}</span>
                <ArrowRight
                  className="size-4 shrink-0 text-muted-foreground group-hover:text-primary"
                  aria-hidden
                />
              </button>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
