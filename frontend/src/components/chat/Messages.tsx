import { CircleAlert, Info, User } from 'lucide-react'
import type { DiagnosisAnswer, Message, ToolCall } from '@/api/types'
import { formatTime } from '@/lib/format'
import { S } from '@/lib/strings'
import { DiagnosisCard } from './DiagnosisCard'
import { StreamingStatus } from './StreamingStatus'
import { ToolCallTimeline } from './ToolCallTimeline'

export function UserMessage({ content, time }: { content: string; time?: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-md border border-info-border bg-info-bg px-3.5 py-2.5">
        <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
          <User className="size-3.5" aria-hidden />
          <span className="font-medium text-info">{S.diagnosis.question}</span>
          {time && <span className="tabular">· {formatTime(time)}</span>}
        </div>
        <p className="whitespace-pre-wrap text-foreground">{content}</p>
      </div>
    </div>
  )
}

export function AssistantMessage({
  content,
  answer,
  toolCalls,
  streaming = false,
  statusText = null,
  error = null,
  time,
}: {
  content?: string
  answer?: DiagnosisAnswer | null
  toolCalls: ToolCall[]
  streaming?: boolean
  statusText?: string | null
  error?: string | null
  time?: string
}) {
  return (
    <div className="space-y-3">
      <ToolCallTimeline toolCalls={toolCalls} streaming={streaming} />
      {streaming && <StreamingStatus text={statusText} />}
      {answer ? (
        <DiagnosisCard answer={answer} time={time} />
      ) : content && !streaming ? (
        // A turn that ended without an answer (stopped, LLM error): the server's note.
        <div className="flex items-start gap-2 rounded-md border border-neutral-border bg-card px-3.5 py-2.5">
          <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <p className="whitespace-pre-wrap">{content}</p>
        </div>
      ) : null}
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-danger-border bg-danger-bg px-3.5 py-2.5 text-danger"
        >
          <CircleAlert className="size-4 shrink-0" aria-hidden />
          {error}
        </div>
      )}
    </div>
  )
}

export function MessageItem({ message }: { message: Message }) {
  if (message.role === 'user')
    return <UserMessage content={message.content} time={message.created_at} />
  return (
    <AssistantMessage
      content={message.content}
      answer={message.answer}
      toolCalls={message.tool_calls}
      time={message.created_at}
    />
  )
}
