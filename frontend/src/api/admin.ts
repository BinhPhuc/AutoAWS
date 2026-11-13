import { api } from './client'
import type { LlmConfig, LlmConfigInput, LlmTestResult } from './types'

/** Admin only (§10): the LLM provider, model and provider keys. */
export const adminApi = {
  getLlm: () => api.get<LlmConfig>('/api/admin/llm'),
  saveLlm: (input: LlmConfigInput) => api.put<LlmConfig>('/api/admin/llm', input),
  resetLlm: () => api.delete<LlmConfig>('/api/admin/llm'),
  testLlm: () => api.post<LlmTestResult>('/api/admin/llm/test'),
}
