import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/client'
import type { AgentEvent, Job } from '@/api/types'
import { initialLiveState, polling, useSendMessage } from './useSendMessage'

const { send, get, cancel } = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), cancel: vi.fn() }))
vi.mock('@/api/conversations', () => ({ conversationsApi: { send } }))
vi.mock('@/api/jobs', () => ({ jobsApi: { get, cancel } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

function job(status: Job['status'], events: AgentEvent[] = [], from = 0): { data: Job } {
  return {
    data: {
      id: 'job_1',
      type: 'diagnosis',
      conversation_id: 'conv_1',
      status,
      cancel_requested: false,
      message_id: null,
      error: null,
      events: events.map((e, i) => ({ ...e, seq: from + i })),
      created_at: '',
      updated_at: '',
    },
  }
}

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

describe('useSendMessage', () => {
  beforeEach(() => {
    // Block body on purpose: a function returned from beforeEach runs as a teardown.
    polling.ms = 1
    send.mockReset()
    get.mockReset()
    cancel.mockReset()
    send.mockResolvedValue(job('queued'))
  })

  it('stops polling and cache updates when sign-out unmounts the chat', async () => {
    let finishPoll!: (value: { data: Job }) => void
    get.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishPoll = resolve
        }),
    )
    const { hook, invalidate } = setup()
    let pending!: Promise<void>
    await act(async () => {
      pending = hook.result.current.send('Check my instance')
    })
    expect(get).toHaveBeenCalledOnce()
    hook.unmount()
    invalidate.mockClear()
    finishPoll(job('running'))
    await pending
    expect(get).toHaveBeenCalledOnce()
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('polls the job, applies its events, then drops the live copy', async () => {
    get
      .mockResolvedValueOnce(
        job('running', [
          { type: 'status', data: { text: 'Reasoning…' } },
          { type: 'tool_call', data: { id: 'tc_1', tool: 'describe_instances', input: {} } },
        ]),
      )
      .mockResolvedValueOnce(
        job(
          'failed',
          [
            {
              type: 'error',
              data: { error: 'LLM_UNAVAILABLE', message: 'LLM provider is unavailable' },
            },
            { type: 'done', data: {} },
          ],
          2,
        ),
      )
    const { hook, invalidate } = setup()
    await act(async () => {
      await hook.result.current.send('Website báo 502')
    })
    expect(send).toHaveBeenCalledWith('conv_1', 'Website báo 502')
    // second poll asks only for events after the last one seen
    expect(get.mock.calls.map((c) => c[1])).toEqual([-1, 1])
    // the server stored the turn: the refreshed conversation shows it, the live copy goes
    expect(hook.result.current.state).toEqual(initialLiveState)
    expect(invalidate).toHaveBeenCalled()
  })

  it('keeps the question and the error when the job could not start', async () => {
    send.mockRejectedValue(
      new ApiError({
        status_code: 409,
        message: 'A diagnosis is already running in this conversation',
        error: 'JOB_IN_PROGRESS',
        path: '/api/conversations/conv_1/messages',
        timestamp: '2026-11-09T00:00:00Z',
      }),
    )
    const { hook } = setup()
    await act(async () => {
      await hook.result.current.send('Không SSH được')
    })
    const s = hook.result.current.state
    expect(s.streaming).toBe(false)
    expect(s.pendingQuestion).toBe('Không SSH được')
    expect(s.error).toBe('A diagnosis is already running in this conversation')
    expect(get).not.toHaveBeenCalled()
  })

  it('stays bound to its conversation, and Stop asks the server to cancel', async () => {
    let finish!: () => void
    const done = new Promise<void>((resolve) => (finish = resolve))
    get.mockImplementation(async (_id: string, after: number) => {
      if (after < 0)
        return job('running', [
          { type: 'tool_call', data: { id: 'tc_1', tool: 'describe_instances', input: {} } },
        ])
      await done
      return job('cancelled', [{ type: 'done', data: {} }], 1)
    })
    cancel.mockResolvedValue(job('running'))
    const { hook } = setup('conv_A')
    let sending!: Promise<void>
    await act(async () => {
      sending = hook.result.current.send('q')
      await new Promise((r) => setTimeout(r, 20))
    })
    expect(hook.result.current.state).toMatchObject({ streaming: true, conversationId: 'conv_A' })
    expect(hook.result.current.state.toolCalls).toHaveLength(1)

    hook.rerender({ id: 'conv_B' })
    expect(hook.result.current.state.conversationId).toBe('conv_A')

    act(() => hook.result.current.stop())
    expect(cancel).toHaveBeenCalledWith('job_1')

    await act(async () => {
      finish()
      await sending
    })
    expect(hook.result.current.state).toEqual(initialLiveState)
  })
})
