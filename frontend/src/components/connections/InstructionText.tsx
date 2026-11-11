export function InstructionText({ text }: { text: string }) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={index} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      )
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code
          key={index}
          className="rounded bg-muted px-1 py-0.5 font-mono text-xs break-all text-foreground"
        >
          {part.slice(1, -1)}
        </code>
      )
    }
    return part
  })
}
