import { describe, expect, it } from 'vitest'
import { createSSEParser, parseSSEBlock } from './sse'
import type { AgentEvent } from './types'

describe('parseSSEBlock', () => {
  it('parses event + data', () => {
    const ev = parseSSEBlock('event: status\ndata: {"text":"Planning checks…"}')
    expect(ev).toEqual({ type: 'status', data: { text: 'Planning checks…' } })
  })

  it('ignores comments and returns null without data', () => {
    expect(parseSSEBlock(': keep-alive')).toBeNull()
    expect(parseSSEBlock('event: done')).toBeNull()
  })

  it('handles empty JSON object for done', () => {
    expect(parseSSEBlock('event: done\ndata: {}')).toEqual({ type: 'done', data: {} })
  })
})

describe('createSSEParser', () => {
  it('splits chunks arriving mid-block', () => {
    const events: AgentEvent[] = []
    const p = createSSEParser((e) => events.push(e))
    p.push('event: tool_call\ndata: {"id":"tc_1","tool":"describe_instances","in')
    p.push(
      'put":{}}\n\nevent: tool_result\ndata: {"id":"tc_1","status":"ok","output_summary":"x","duration_ms":5}\n\n',
    )
    p.push('event: done\ndata: {}')
    p.flush()
    expect(events.map((e) => e.type)).toEqual(['tool_call', 'tool_result', 'done'])
    expect(events[0]).toMatchObject({ data: { tool: 'describe_instances' } })
  })

  it('supports CRLF separators', () => {
    const events: AgentEvent[] = []
    const p = createSSEParser((e) => events.push(e))
    p.push('event: status\r\ndata: {"text":"a"}\r\n\r\nevent: status\r\ndata: {"text":"b"}\r\n\r\n')
    expect(events).toHaveLength(2)
  })
})
