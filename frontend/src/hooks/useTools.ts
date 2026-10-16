import { useQuery } from '@tanstack/react-query'
import { toolsApi } from '@/api/tools'
import type { ToolSpec } from '@/api/types'

export function useTools() {
  return useQuery({
    queryKey: ['tools'],
    queryFn: async () => (await toolsApi.list()).data,
    staleTime: 5 * 60 * 1000,
  })
}

/** Lookup helper: tool name → spec (label/group). Falls back to the raw name. */
export function useToolLookup() {
  const { data } = useTools()
  const map = new Map<string, ToolSpec>((data ?? []).map((t) => [t.name, t]))
  return (name: string) =>
    map.get(name) ??
    ({
      name,
      label: name,
      group: 'compute',
      description: '',
      input_schema: {},
      aws_actions: [],
    } as ToolSpec)
}
