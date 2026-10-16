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
  /** The question currently being processed (rendered optimistically). */
  pendingQuestion: string | null
  statusText: string | null
  toolCalls: ToolCall[]
  answer: { content: string; answer: DiagnosisAnswer } | null
  error: string | null
}

const initial: LiveState = {
  streaming: false,
  pendingQuestion: null,
  statusText: null,
  toolCalls: [],
  answer: null,
  error: null,
}

/** Sends a message and exposes the live streaming state for the UI. */
export function useSendMessage(conversationId: string | undefined) {
  const qc = useQueryClient()
  const [state, setState] = useState<LiveState>(initial)
  const abortRef = useRef<AbortController | null>(null)

  const reset = useCallback(() => setState(initial), [])

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const send = useCallback(
    async (content: string) => {
      if (!conversationId || !content.trim()) return
      const controller = new AbortController()
      abortRef.current = controller
      setState({
        ...initial,
        streaming: true,
        pendingQuestion: content,
        statusText: S.chat.thinking,
      })

      const started = new Map<string, number>()
      const onEvent = (e: AgentEvent) => {
        setState((prev) => {
          switch (e.type) {
            case 'status':
              return { ...prev, statusText: e.data.text }
            case 'tool_call': {
              started.set(e.data.id, Date.now())
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
        if (controller.signal.aborted) {
          // user cancelled; keep what we have
        } else {
          const msg = err instanceof ApiError ? err.message : S.chat.streamError
          setState((prev) => ({ ...prev, error: msg }))
          toast.error(msg)
        }
      } finally {
        abortRef.current = null
        // Refresh the persisted conversation, then clear live state once the server copy is in cache.
        await qc.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) })
        await qc.invalidateQueries({ queryKey: conversationKeys.all })
        setState((prev) => (prev.error ? { ...prev, streaming: false } : initial))
      }
    },
    [conversationId, qc],
  )

  return { state, send, stop, reset }
}
