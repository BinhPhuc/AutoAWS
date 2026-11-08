import { Loader2 } from 'lucide-react'

export function StreamingStatus({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <div
      role="status"
      className="flex items-center gap-2 rounded-md border border-info-border bg-info-bg px-3.5 py-2 text-info"
    >
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span>{text}</span>
    </div>
  )
}
