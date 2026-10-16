import { API_BASE, toApiError } from './client'
import type { AgentEvent } from './types'

/**
 * Parses one SSE block ("event: x\ndata: {...}") into an AgentEvent.
 * Returns null for comments / blocks without data.
 */
export function parseSSEBlock(block: string): AgentEvent | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line || line.startsWith(':')) continue
    const idx = line.indexOf(':')
    const field = idx === -1 ? line : line.slice(0, idx)
    const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
  }
  if (dataLines.length === 0) return null
  const raw = dataLines.join('\n')
  let data: unknown = {}
  if (raw.trim()) {
    try {
      data = JSON.parse(raw)
    } catch {
      return null
    }
  }
  return { type: event, data } as AgentEvent
}

/**
 * Splits an incoming text chunk stream into SSE blocks separated by a blank line.
 * Exposed for tests.
 */
export function createSSEParser(onEvent: (e: AgentEvent) => void) {
  let buffer = ''
  return {
    push(chunk: string) {
      buffer += chunk
      let idx: number
      while ((idx = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const sepLen = buffer.startsWith('\r\n', idx) ? 4 : 2
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + sepLen)
        const ev = parseSSEBlock(block)
        if (ev) onEvent(ev)
      }
    },
    flush() {
      if (buffer.trim()) {
        const ev = parseSSEBlock(buffer)
        if (ev) onEvent(ev)
      }
      buffer = ''
    },
  }
}

/**
 * POST a JSON body and consume the SSE response via ReadableStream.
 * Errors before the stream starts are thrown as ApiError; errors mid-stream arrive as `error` events.
 * Resolves when the stream is closed.
 */
export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw await toApiError(res, path)
  if (!res.body) throw new Error('Response has no body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parser = createSSEParser(onEvent)
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      parser.push(decoder.decode(value, { stream: true }))
    }
    parser.push(decoder.decode())
    parser.flush()
  } finally {
    reader.releaseLock()
  }
}
