import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import { conversationsApi } from '@/api/conversations'
import { jobsApi } from '@/api/jobs'
import type { AgentEvent, DiagnosisAnswer, Job, ToolCall } from '@/api/types'
import { S } from '@/lib/strings'
import { conversationKeys } from './useConversations'

export interface LiveState {
  streaming: boolean
  /** Conversation the live turn belongs to; the UI renders it only there. */
  conversationId: string | null
  /** The question currently being processed (rendered optimistically). */
  pendingQuestion: string | null
  statusText: string | null
  toolCalls: ToolCall[]
  answer: { content: string; answer: DiagnosisAnswer } | null
  error: string | null
}

export const initialLiveState: LiveState = {
  streaming: false,
  conversationId: null,
  pendingQuestion: null,
  statusText: null,
  toolCalls: [],
  answer: null,
  error: null,
}

/** Delay between job polls (API_CONTRACT §3: every 1–2 s). Tests lower it. */
export const polling = { ms: 1000 }

const ACTIVE: Job['status'][] = ['queued', 'running']

/** Applies one job event to the live state. */
function reduce(prev: LiveState, e: AgentEvent): LiveState {
  switch (e.type) {
    case 'status':
      return { ...prev, statusText: e.data.text }
    case 'tool_call': {
      const tc: ToolCall = {
        id: e.data.id,
        tool: e.data.tool,
        input: e.data.input,
        output_summary: '',
        status: 'ok',
        error: null,
        duration_ms: 0,
      }
      return { ...prev, toolCalls: [...prev.toolCalls, tc] }
    }
    case 'tool_result':
      return {
        ...prev,
        toolCalls: prev.toolCalls.map((tc) =>
          tc.id === e.data.id
            ? {
                ...tc,
                status: e.data.status,
                output_summary: e.data.output_summary,
                duration_ms: e.data.duration_ms,
                cached: e.data.cached ?? false,
                error: e.data.status === 'error' ? e.data.output_summary : null,
              }
            : tc,
        ),
      }
    case 'answer':
      return {
        ...prev,
        statusText: null,
        answer: { content: e.data.content, answer: e.data.answer },
      }
    case 'error':
      return { ...prev, statusText: null, error: e.data.message }
    case 'done':
      return { ...prev, statusText: null }
    default:
      return prev
  }
}

/** Starts a diagnosis job and polls it, exposing the live state for the UI. */
export function useSendMessage(conversationId: string | undefined) {
  const qc = useQueryClient()
  const [state, setState] = useState<LiveState>(initialLiveState)
  const jobRef = useRef<string | null>(null)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const reset = useCallback(() => setState(initialLiveState), [])

  /** Asks the worker to stop; polling continues until the server ends the turn. */
  const stop = useCallback(() => {
    const id = jobRef.current
    if (!id) return
    setState((prev) => ({ ...prev, statusText: S.chat.stopping }))
    void jobsApi.cancel(id).catch(() => undefined)
  }, [])

  const send = useCallback(
    async (content: string) => {
      if (!conversationId || !content.trim()) return
      setState({
        ...initialLiveState,
        streaming: true,
        conversationId,
        pendingQuestion: content,
        statusText: S.chat.thinking,
      })

      let job: Job
      try {
        job = (await conversationsApi.send(conversationId, content)).data
        if (!mounted.current) return
      } catch (err) {
        if (!mounted.current) return
        // Nothing was stored: keep the question and the error on screen.
        const msg = err instanceof ApiError ? err.message : S.chat.streamError
        setState((prev) => ({ ...prev, streaming: false, statusText: null, error: msg }))
        toast.error(msg)
        return
      }
      jobRef.current = job.id
      // The question is stored and the title set when the job starts: refresh the list.
      void qc.invalidateQueries({ queryKey: conversationKeys.lists() })

      let lastSeq = -1
      let failures = 0
      try {
        for (;;) {
          if (!mounted.current) return
          let fresh: Job
          try {
            fresh = (await jobsApi.get(job.id, lastSeq)).data
            if (!mounted.current) return
            failures = 0
          } catch {
            if (!mounted.current) return
            if (++failures >= 5) throw new Error(S.chat.streamError)
            await new Promise((r) => setTimeout(r, polling.ms))
            continue
          }
          for (const e of fresh.events) {
            if (e.seq <= lastSeq) continue
            lastSeq = e.seq
            if (e.type === 'error' && e.data.error !== 'CANCELLED') toast.error(e.data.message)
            setState((prev) => reduce(prev, e))
          }
          if (!ACTIVE.includes(fresh.status)) break
          await new Promise((r) => setTimeout(r, polling.ms))
        }
      } catch (err) {
        if (!mounted.current) return
        const msg = err instanceof Error ? err.message : S.chat.streamError
        setState((prev) => ({ ...prev, error: msg }))
        toast.error(msg)
      } finally {
        jobRef.current = null
        if (mounted.current) {
          // Refresh the persisted conversation, then drop the live copy once the server copy
          // is in cache (the server stores every turn, answered or not - API_CONTRACT §3).
          await qc.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) })
          await qc.invalidateQueries({ queryKey: conversationKeys.all })
          void qc.invalidateQueries({ queryKey: ['proposals'] })
          setState(initialLiveState)
        }
      }
    },
    [conversationId, qc],
  )

  return { state, send, stop, reset }
}
