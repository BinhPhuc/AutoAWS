// Mirror of docs/API_CONTRACT.md. Keep this file as the single source of API types.

// ---------- Envelope ----------
export interface Envelope<T> {
  status_code: number
  message: string
  data: T
}

export interface ApiErrorBody {
  status_code: number
  message: string
  error: ApiErrorCode | string
  path: string
  timestamp: string
}

export type ApiErrorCode =
  | 'VALIDATION_ERROR'
  | 'CONNECTION_NOT_FOUND'
  | 'CONVERSATION_NOT_FOUND'
  | 'CONNECTION_NOT_VERIFIED'
  | 'AWS_AUTH_FAILED'
  | 'AWS_ACCESS_DENIED'
  | 'LLM_UNAVAILABLE'
  | 'MAX_ITERATIONS'
  | 'AGENT_LIMIT'
  | 'NOT_FOUND'
  | 'METHOD_NOT_ALLOWED'
  | 'NOT_IMPLEMENTED'
  | 'INTERNAL'

// ---------- Health ----------
export interface Health {
  status: 'ok'
  version: string
  llm_provider: 'mock' | 'anthropic' | 'bedrock' | 'mcp'
}

// ---------- Connections ----------
export type ConnectionType = 'access_key' | 'role'
export type ConnectionStatus = 'pending' | 'connected' | 'failed'

export interface Connection {
  id: string
  name: string
  type: ConnectionType
  region: string
  status: ConnectionStatus
  account_id: string | null
  role_arn: string | null
  external_id: string | null
  access_key_id_masked: string | null
  last_verified_at: string | null
  last_error: string | null
  created_at: string
}

export interface CreateAccessKeyConnection {
  type: 'access_key'
  name: string
  region: string
  access_key_id: string
  secret_access_key: string
}

export interface CreateRoleConnection {
  type: 'role'
  name: string
  region: string
  role_arn: string
  external_id?: string
}

export type CreateConnectionInput = CreateAccessKeyConnection | CreateRoleConnection

export interface VerifyResult {
  status: 'connected' | 'failed'
  account_id: string | null
  arn: string | null
  checked_at: string
  error: string | null
}

export interface CloudFormationInfo {
  stack_name: string
  role_name: string
  external_id: string
  platform_account_id: string
  template_yaml: string
}

// ---------- Conversations ----------
export type Confidence = 'high' | 'medium' | 'low'

/** Set by the server from the tool results it saw (API_CONTRACT §3). */
export type Verification = 'read' | 'inferred' | 'not_found'

export interface Evidence {
  text: string
  source: string
  resource_id?: string | null
  field?: string | null
  value?: string | null
  verified: boolean
  verification?: Verification | null
}

export interface RootCause {
  statement: string
  confidence: Confidence
  evidence: Evidence[]
}

export interface Unverified {
  text: string
  how_to_check: string
}

export type LimitReached = 'max_iterations' | 'time' | 'tokens' | 'tool_calls'

export interface DiagnosisAnswer {
  summary: string
  root_causes: RootCause[]
  fix_steps: string[]
  unverified: Unverified[]
  confidence: Confidence
  limit_reached?: LimitReached | null
}

export interface ToolCall {
  id: string
  tool: string
  input: Record<string, unknown>
  output_summary: string
  status: 'ok' | 'error'
  error: string | null
  duration_ms: number
  cached?: boolean
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  answer: DiagnosisAnswer | null
  tool_calls: ToolCall[]
  created_at: string
}

export interface Conversation {
  id: string
  connection_id: string
  title: string
  created_at: string
  updated_at: string
  messages?: Message[]
}

export interface CreateConversationInput {
  connection_id: string
}

export interface SendMessageInput {
  content: string
}

// ---------- SSE events ----------
export interface StatusEvent {
  type: 'status'
  data: { text: string }
}
export interface ToolCallEvent {
  type: 'tool_call'
  data: { id: string; tool: string; input: Record<string, unknown> }
}
export interface ToolResultEvent {
  type: 'tool_result'
  data: {
    id: string
    status: 'ok' | 'error'
    output_summary: string
    duration_ms: number
    cached?: boolean
  }
}
export interface AnswerEvent {
  type: 'answer'
  data: { message_id: string; content: string; answer: DiagnosisAnswer }
}
export interface ErrorEvent {
  type: 'error'
  data: { error: ApiErrorCode | string; message: string }
}
export interface DoneEvent {
  type: 'done'
  data: Record<string, never>
}

export type AgentEvent =
  StatusEvent | ToolCallEvent | ToolResultEvent | AnswerEvent | ErrorEvent | DoneEvent

// ---------- Tools ----------
export type ToolGroup = 'compute' | 'network' | 'dns' | 'elb' | 'metrics' | 'logs' | 'cloudtrail'

export interface ToolSpec {
  name: string
  group: ToolGroup
  label: string
  description: string
  input_schema: Record<string, unknown>
  aws_actions: string[]
}
