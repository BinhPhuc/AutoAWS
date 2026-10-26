import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/client'
import type { AgentEvent } from '@/api/types'
import { initialLiveState, useSendMessage } from './useSendMessage'

const streamSSE = vi.fn()
vi.mock('@/api/sse', () => ({ streamSSE: (...args: unknown[]) => streamSSE(...args) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

type OnEvent = (e: AgentEvent) => void

function setup(conversationId = 'conv_1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, 'invalidateQueries')
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  const hook = renderHook(({ id }: { id: string }) => useSendMessage(id), {
    wrapper,
    initialProps: { id: conversationId },
  })
  return { hook, invalidate }
}

function emits(...events: AgentEvent[]) {
  return async (_path: string, _body: unknown, onEvent: OnEvent) => {
    for (const e of events) onEvent(e)
  }
}

describe('useSendMessage', () => {
  beforeEach(() => {
    // Block body on purpose: a function returned from beforeEach runs as a teardown.
    streamSSE.mockReset()
  })

  it('drops the live copy once streaming started, even when the turn failed', async () => {
    streamSSE.mockImplementation(
      emits(
        { type: 'status', data: { text: 'Reasoning…' } },
        {
          type: 'error',
          data: { error: 'LLM_UNAVAILABLE', message: 'LLM provider is unavailable' },
        },
        { type: 'done', data: {} },
      ),
    )
    const { hook, invalidate } = setup()
    await act(async () => {
      await hook.result.current.send('Website báo 502')
    })
    // The server stored the question and a note for the failed turn: the refreshed
    // conversation shows them, so the live copy must go (no duplicated question).
    expect(hook.result.current.state).toEqual(initialLiveState)
    expect(invalidate).toHaveBeenCalled()
  })

  it('keeps the question and the error when the request failed before streaming', async () => {
    streamSSE.mockRejectedValue(
      new ApiError({
        status_code: 400,
        message: 'Connection is not verified yet',
        error: 'CONNECTION_NOT_VERIFIED',
        path: '/api/conversations/conv_1/messages',
        timestamp: '2026-10-26T00:00:00Z',
      }),
    )
    const { hook } = setup()
    await act(async () => {
      await hook.result.current.send('Không SSH được')
    })
    const s = hook.result.current.state
    expect(s.streaming).toBe(false)
    expect(s.pendingQuestion).toBe('Không SSH được')
    expect(s.error).toBe('Connection is not verified yet')
  })

  it('keeps the live turn bound to its conversation when the page switches', async () => {
    let finish!: () => void
    streamSSE.mockImplementation(async (_path: string, _body: unknown, onEvent: OnEvent) => {
      onEvent({ type: 'tool_call', data: { id: 'tc_1', tool: 'describe_instances', input: {} } })
      await new Promise<void>((resolve) => (finish = resolve))
    })
    const { hook } = setup('conv_A')
    let sending!: Promise<void>
    await act(async () => {
      sending = hook.result.current.send('q')
    })
    expect(hook.result.current.state).toMatchObject({ streaming: true, conversationId: 'conv_A' })

    hook.rerender({ id: 'conv_B' })
    expect(hook.result.current.state.conversationId).toBe('conv_A')

    await act(async () => {
      finish()
      await sending
    })
    expect(hook.result.current.state).toEqual(initialLiveState)
  })
})
