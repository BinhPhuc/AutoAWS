import { Loader2 } from 'lucide-react'

export function StreamingStatus({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground" role="status">
      <Loader2 className="size-4 animate-spin" />
      <span>{text}</span>
    </div>
  )
}
