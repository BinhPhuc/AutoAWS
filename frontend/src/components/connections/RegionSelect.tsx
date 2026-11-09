import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { AWS_REGIONS } from '@/lib/format'
import { S } from '@/lib/strings'

const regionNames: Readonly<Record<string, string>> = S.connections.regionNames

export function RegionSelect({
  value,
  onChange,
  id,
}: {
  value: string
  onChange: (v: string) => void
  id?: string
}) {
  return (
    <Select value={value} onValueChange={(v) => v && onChange(String(v))}>
      <SelectTrigger id={id} className="h-10 w-full bg-background px-3">
        <SelectValue>
          <span>{regionNames[value] ?? value}</span>
          <span className="ml-2 font-mono text-xs text-muted-foreground">{value}</span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent
        side="bottom"
        align="start"
        sideOffset={6}
        alignItemWithTrigger={false}
        collisionAvoidance={{ side: 'none', align: 'shift' }}
        className="max-h-[min(16rem,var(--available-height))] p-1 shadow-lg"
      >
        {AWS_REGIONS.map((r) => (
          <SelectItem
            key={r}
            value={r}
            className="cursor-pointer py-2 pr-10 pl-3 data-highlighted:bg-accent"
          >
            <span className="flex min-w-0 flex-1 items-center justify-between gap-4">
              <span>{regionNames[r]}</span>
              <span className="font-mono text-xs text-muted-foreground">{r}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
