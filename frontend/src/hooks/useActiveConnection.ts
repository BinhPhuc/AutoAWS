import { useCallback, useEffect, useState } from 'react'
import type { Connection } from '@/api/types'

const STORAGE_KEY = 'autoaws.activeConnectionId'

function read(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function write(id: string | null) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

// Tiny cross-component store so Sidebar and ChatPage agree on the active connection.
let current: string | null = read()
const listeners = new Set<() => void>()
function setCurrent(id: string | null) {
  current = id
  write(id)
  listeners.forEach((l) => l())
}

export function clearActiveConnection() {
  setCurrent(null)
}

/**
 * Active connection = stored choice if it is still a connected connection,
 * otherwise the first connected one.
 */
export function useActiveConnection(connections: Connection[] | undefined) {
  const [, force] = useState(0)
  useEffect(() => {
    const l = () => force((n) => n + 1)
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  }, [])

  const connected = (connections ?? []).filter((c) => c.status === 'connected')
  const valid = current && connected.some((c) => c.id === current) ? current : null
  const activeConnectionId = valid ?? connected[0]?.id ?? null

  const setActiveConnectionId = useCallback((id: string | null) => setCurrent(id), [])

  return { activeConnectionId, setActiveConnectionId, connectedConnections: connected }
}
