import { useEffect, useRef, useState } from 'react'
import { SendHorizontal, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { S } from '@/lib/strings'

export function Composer({
  onSend,
  onStop,
  disabled,
  streaming,
  initialValue = '',
}: {
  onSend: (text: string) => void
  onStop?: () => void
  disabled?: boolean
  streaming?: boolean
  /** When this changes to a non-empty value the textarea is prefilled (used by example buttons). */
  initialValue?: string
}) {
  const [value, setValue] = useState('')
  const [appliedPrefill, setAppliedPrefill] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  // Adjust state when the prefill prop changes (React's "derived state" pattern, no effect needed).
  if (initialValue && initialValue !== appliedPrefill) {
    setAppliedPrefill(initialValue)
    setValue(initialValue)
  }
  useEffect(() => {
    if (appliedPrefill) ref.current?.focus()
  }, [appliedPrefill])

  const submit = () => {
    const text = value.trim()
    if (!text || disabled || streaming) return
    onSend(text)
    setValue('')
  }

  return (
    <form
      className="flex items-end gap-2 border-t bg-background p-3"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <Textarea
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder={S.chat.composerPlaceholder}
        rows={2}
        disabled={disabled || streaming}
        className="max-h-40 min-h-10 resize-none"
      />
      {streaming ? (
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={S.chat.stop}
          onClick={onStop}
        >
          <Square />
        </Button>
      ) : (
        <Button
          type="submit"
          size="icon"
          aria-label={S.chat.send}
          disabled={disabled || !value.trim()}
        >
          <SendHorizontal />
        </Button>
      )}
    </form>
  )
}
