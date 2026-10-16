import { Bot, CircleAlert, User } from 'lucide-react'
import type { DiagnosisAnswer, Message, ToolCall } from '@/api/types'
import { formatTime } from '@/lib/format'
import { DiagnosisCard } from './DiagnosisCard'
import { StreamingStatus } from './StreamingStatus'
import { ToolCallTimeline } from './ToolCallTimeline'

export function UserMessage({ content, time }: { content: string; time?: string }) {
  return (
    <div className="flex justify-end gap-2">
      <div className="max-w-[85%] space-y-0.5">
        <div className="rounded-2xl rounded-tr-sm bg-primary px-3.5 py-2 text-sm whitespace-pre-wrap text-primary-foreground">
          {content}
        </div>
        {time && (
          <div className="text-right text-[10px] text-muted-foreground">{formatTime(time)}</div>
        )}
      </div>
      <div className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
        <User className="size-4" />
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
    <div className="flex gap-2">
      <div className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
        <Bot className="size-4" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <ToolCallTimeline toolCalls={toolCalls} streaming={streaming} />
        {streaming && <StreamingStatus text={statusText} />}
        {answer ? (
          <DiagnosisCard answer={answer} />
        ) : content && !streaming ? (
          <p className="text-sm whitespace-pre-wrap">{content}</p>
        ) : null}
        {error && (
          <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <CircleAlert className="size-4" />
            {error}
          </div>
        )}
        {time && !streaming && (
          <div className="text-[10px] text-muted-foreground">{formatTime(time)}</div>
        )}
      </div>
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
