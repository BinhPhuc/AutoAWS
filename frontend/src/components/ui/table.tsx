import { cn } from '@/lib/utils'

/** Dense data table (dashboard style): grey header row, hairline row borders, row hover. */
export function Table({ className, ...props }: React.ComponentProps<'table'>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn('w-full border-collapse text-sm', className)} {...props} />
    </div>
  )
}

export function THead({ className, ...props }: React.ComponentProps<'thead'>) {
  return <thead className={cn('bg-muted', className)} {...props} />
}

export function TBody(props: React.ComponentProps<'tbody'>) {
  return <tbody {...props} />
}

export function Tr({ className, ...props }: React.ComponentProps<'tr'>) {
  return (
    <tr
      className={cn('border-b last:border-b-0 hover:bg-muted/60 [thead_&]:hover:bg-transparent', className)}
      {...props}
    />
  )
}

export function Th({ className, ...props }: React.ComponentProps<'th'>) {
  return (
    <th
      scope="col"
      className={cn(
        'border-b px-3 py-2 text-left text-xs font-semibold whitespace-nowrap text-muted-foreground',
        className,
      )}
      {...props}
    />
  )
}

export function Td({ className, ...props }: React.ComponentProps<'td'>) {
  return <td className={cn('px-3 py-2 align-top', className)} {...props} />
}

/** Monospace identifier (resource ids, tool names, ARNs): wraps instead of overflowing. */
export function Mono({ className, ...props }: React.ComponentProps<'code'>) {
  return (
    <code
      className={cn('font-mono text-xs [overflow-wrap:anywhere] text-foreground/90', className)}
      {...props}
    />
  )
}
