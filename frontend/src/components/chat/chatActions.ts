import { createContext, useContext } from 'react'

/** Actions a deep child (a proposal card) can trigger in the open conversation. */
export const ChatActionsContext = createContext<{ followup?: (question: string) => void }>({})

export function useChatActions() {
  return useContext(ChatActionsContext)
}
