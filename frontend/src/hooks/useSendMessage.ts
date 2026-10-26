import { useCallback, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import { conversationsApi } from '@/api/conversations'
import { streamSSE } from '@/api/sse'
import type { AgentEvent, DiagnosisAnswer, ToolCall } from '@/api/types'
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

/** After Stop, give the server a moment to store the stopped turn before refetching. */
const STOP_SETTLE_MS = 400

/** Sends a message and exposes the live streaming state for the UI. */
export function useSendMessage(conversationId: string | undefined) {
  const qc = useQueryClient()
  const [state, setState] = useState<LiveState>(initialLiveState)
  const abortRef = useRef<AbortController | null>(null)

  const reset = useCallback(() => setState(initialLiveState), [])

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const send = useCallback(
    async (content: string) => {
      if (!conversationId || !content.trim()) return
      const controller = new AbortController()
      abortRef.current = controller
      setState({
        ...initialLiveState,
        streaming: true,
        conversationId,
        pendingQuestion: content,
        statusText: S.chat.thinking,
      })

      // The first SSE event means the server has stored the question; from then on it also
      // stores the turn's outcome (answer, or a note when it ends early - API_CONTRACT §3).
      let streamStarted = false
      const onEvent = (e: AgentEvent) => {
        if (!streamStarted) {
          streamStarted = true
          // The title is set when the turn starts: refresh the sidebar list right away.
          void qc.invalidateQueries({ queryKey: conversationKeys.lists() })
        }
        if (e.type === 'error') toast.error(e.data.message)
        setState((prev) => {
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
        })
      }

      try {
        await streamSSE(
          conversationsApi.messagesPath(conversationId),
          { content },
          onEvent,
          controller.signal,
        )
      } catch (err) {
        if (!controller.signal.aborted) {
          const msg = err instanceof ApiError ? err.message : S.chat.streamError
          setState((prev) => ({ ...prev, error: msg }))
          toast.error(msg)
        }
      } finally {
        abortRef.current = null
        const stopped = controller.signal.aborted
        if (stopped) await new Promise((r) => setTimeout(r, STOP_SETTLE_MS))
        // Refresh the persisted conversation, then drop the live copy once the server copy is
        // in cache. If the request failed before streaming, nothing was stored: keep the
        // question and the error on screen instead.
        await qc.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) })
        await qc.invalidateQueries({ queryKey: conversationKeys.all })
        setState((prev) =>
          streamStarted || stopped ? initialLiveState : { ...prev, streaming: false },
        )
      }
    },
    [conversationId, qc],
  )

  return { state, send, stop, reset }
}
