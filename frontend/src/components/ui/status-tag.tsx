import { cn } from '@/lib/utils'

export type Tone = 'success' | 'info' | 'warning' | 'danger' | 'neutral'

const toneClass: Record<Tone, string> = {
  success: 'border-success-border bg-success-bg text-success',
  info: 'border-info-border bg-info-bg text-info',
  warning: 'border-warning-border bg-warning-bg text-warning',
  danger: 'border-danger-border bg-danger-bg text-danger',
  neutral: 'border-neutral-border bg-neutral-bg text-neutral',
}

const dotClass: Record<Tone, string> = {
  success: 'bg-success',
  info: 'bg-info',
  warning: 'bg-warning',
  danger: 'bg-danger',
  neutral: 'bg-neutral',
}

/**
 * The one status tag used everywhere (connection status, tool result, confidence, evidence
 * check…). Tone carries the colour; the label always carries the meaning as text.
 */
export function StatusTag({
  tone,
  children,
  dot = false,
  title,
  className,
}: {
  tone: Tone
  children: React.ReactNode
  dot?: boolean
  title?: string
  className?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border px-1.5 text-xs leading-none font-medium whitespace-nowrap [&>svg]:size-3',
        toneClass[tone],
        className,
      )}
    >
      {dot && <span aria-hidden className={cn('size-1.5 rounded-full', dotClass[tone])} />}
      {children}
    </span>
  )
}
