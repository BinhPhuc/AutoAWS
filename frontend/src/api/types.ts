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
  | 'EXTERNAL_ID_INVALID'
  | 'EXTERNAL_ID_IN_USE'
  | 'UNAUTHORIZED'
  | 'VALIDATION_ERROR'
  | 'CONNECTION_NOT_FOUND'
  | 'CONNECTION_SETUP_UNAVAILABLE'
  | 'CONVERSATION_NOT_FOUND'
  | 'CONNECTION_NOT_VERIFIED'
  | 'AWS_AUTH_FAILED'
  | 'AWS_ACCESS_DENIED'
  | 'LLM_UNAVAILABLE'
  | 'MAX_ITERATIONS'
  | 'AGENT_LIMIT'
  | 'JOB_NOT_FOUND'
  | 'JOB_IN_PROGRESS'
  | 'PROPOSAL_NOT_FOUND'
  | 'PROPOSAL_NOT_PENDING'
  | 'REMEDIATION_DISABLED'
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

// ---------- Sign-in (contract §0.1) ----------
export interface AuthConfig {
  mode: 'none' | 'cognito'
  /** Hosted UI base URL, e.g. https://x.auth.ap-southeast-1.amazoncognito.com */
  domain: string | null
  client_id: string | null
  scopes: string[]
}

export interface Me {
  user_id: string
  username: string
  auth_mode: 'none' | 'cognito'
}

// ---------- Connections ----------
export type ConnectionType = 'access_key' | 'role'
export type ConnectionStatus = 'pending' | 'connected' | 'failed'

export interface ConnectionSetup {
  account_id: string | null
  role_name: string
  trust_principals: string[]
  /** Issued by the server for the signed-in user; the only value create accepts. */
  external_id: string
  /** Region the connection form starts with (server DEFAULT_REGION). */
  default_region: string
}

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
  remediation_role_arn: string | null
  /** Server: approved proposals can be executed on this connection. */
  remediation_enabled: boolean
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
  remediation_role_arn?: string
}

export type CreateConnectionInput = CreateAccessKeyConnection | CreateRoleConnection

/** PATCH /api/connections/{id}: only the fields sent change. `type` and `external_id` are
 * fixed; a new region or role ARN puts the connection back to `pending` (verify again). */
export interface ConnectionPatch {
  name?: string
  region?: string
  /** Role connections only. */
  role_arn?: string
  /** Role connections only; null turns remediation off. */
  remediation_role_arn?: string | null
}

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

/** A catalogue fix the agent proposed; the server fills proposal_id or error (§7). */
export interface ProposalRef {
  action: string
  params: Record<string, unknown>
  reason: string
  proposal_id: string | null
  error: string | null
}

export interface DiagnosisAnswer {
  summary: string
  root_causes: RootCause[]
  fix_steps: string[]
  unverified: Unverified[]
  confidence: Confidence
  proposals?: ProposalRef[]
  limit_reached?: LimitReached | null
}

// ---------- Remediation (human-in-the-loop) ----------
export type ProposalStatus =
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'EXECUTING'
  | 'SUCCEEDED'
  | 'REJECTED'
  | 'EXPIRED'
  | 'SUPERSEDED'
  | 'STALE'
  | 'FAILED'
  | 'VERIFY_FAILED'
  | 'ROLLED_BACK'

export interface ProposalPreview {
  summary: string
  changes: { field: string; before: string; after: string }[]
  impact: string
  risk: 'low' | 'medium' | 'high'
  rollback: string
  verify: string
}

export interface Proposal {
  id: string
  conversation_id: string
  message_id: string
  connection_id: string
  kind: 'fix' | 'rollback'
  parent_id: string | null
  action: string
  params: Record<string, unknown>
  reason: string
  status: ProposalStatus
  preview: ProposalPreview
  result: Record<string, unknown> | null
  verification: { ok: boolean; details: string } | null
  error: string | null
  /** `by`: user id of whoever decided (approve / reject / feedback) */
  history: { status: ProposalStatus; at: string; note: string; by?: string | null }[]
  created_at: string
  updated_at: string
  expires_at: string | null
}

export type Decision = 'approve' | 'reject' | 'feedback'

export interface DecisionResult {
  proposal: Proposal
  followup_question: string | null
}

export interface RemediationAction {
  name: string
  label: string
  description: string
  input_schema: Record<string, unknown>
  aws_actions: string[]
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

// ---------- Job events (API_CONTRACT §3, §8) ----------
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

export type JobEvent = AgentEvent & { seq: number }

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

/** A background diagnosis turn; the client polls it (API_CONTRACT §8). */
export interface Job {
  id: string
  type: 'diagnosis'
  conversation_id: string
  status: JobStatus
  cancel_requested: boolean
  message_id: string | null
  error: { error: ApiErrorCode | string; message: string } | null
  events: JobEvent[]
  created_at: string
  updated_at: string
}

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
