import { HttpResponse, delay, http } from 'msw'
import type {
  AgentEvent,
  ApiErrorBody,
  CloudFormationInfo,
  Connection,
  Conversation,
  CreateConnectionInput,
  CreateConversationInput,
  DiagnosisAnswer,
  Job,
  Message,
  Proposal,
  SendMessageInput,
  ToolCall,
  VerifyResult,
} from '@/api/types'
import { db, nextId, seed, tools } from './db'
import { pickScenario, scenarioEvents } from './scenarios'

const STOPPED_NOTE = 'Lượt chẩn đoán đã bị dừng trước khi có kết luận.'

seed()

const now = () => new Date().toISOString()

function ok<T>(data: T, message = 'OK', status_code = 200) {
  return HttpResponse.json({ status_code, message, data }, { status: status_code })
}

function fail(status_code: number, error: string, message: string, path: string) {
  const body: ApiErrorBody = { status_code, message, error, path, timestamp: now() }
  return HttpResponse.json(body, { status: status_code })
}

const pathOf = (req: Request) => new URL(req.url).pathname

export const handlers = [
  http.get('/api/health', async () => {
    await delay(100)
    return ok({ status: 'ok', version: '0.1.0-mock', llm_provider: 'mock' })
  }),
  // The mock runs without sign-in (AUTH_MODE=none)
  http.get('/api/auth/config', () =>
    ok({ mode: 'none', domain: null, client_id: null, scopes: [] }),
  ),
  http.get('/api/me', () => ok({ user_id: 'local', username: 'local', auth_mode: 'none' })),

  // ---------- connections ----------
  http.get('/api/connections/setup', () =>
    ok({
      account_id: '111122223333',
      role_name: 'AutoAWSReadOnly',
      trust_principals: ['arn:aws:iam::111122223333:root'],
    }),
  ),
  http.post('/api/connections/cloudformation-preview', async ({ request }) => {
    const { external_id } = (await request.json()) as { external_id: string }
    if (!/^[A-Za-z0-9_+=,.@:/-]{2,1224}$/.test(external_id))
      return fail(422, 'VALIDATION_ERROR', 'Invalid External ID', pathOf(request))
    return ok({
      stack_name: 'AutoAWSReadOnlyRole',
      role_name: 'AutoAWSReadOnly',
      external_id,
      platform_account_id: '111122223333',
      template_yaml: cfnTemplate(external_id),
    })
  }),
  http.get('/api/connections', async () => {
    await delay(150)
    return ok(db.connections)
  }),

  http.get('/api/connections/:id', async ({ params, request }) => {
    const c = db.connections.find((x) => x.id === params.id)
    if (!c) return fail(404, 'CONNECTION_NOT_FOUND', 'Connection not found', pathOf(request))
    return ok(c)
  }),

  http.post('/api/connections', async ({ request }) => {
    const body = (await request.json()) as CreateConnectionInput
    await delay(300)
    if (!body.name?.trim())
      return fail(422, 'VALIDATION_ERROR', 'Invalid request: name is required', pathOf(request))
    const conn: Connection = {
      id: nextId('conn'),
      name: body.name,
      type: body.type,
      region: body.region,
      status: 'pending',
      account_id: null,
      role_arn: body.type === 'role' ? body.role_arn : null,
      external_id:
        body.type === 'role' ? (body.external_id ?? `autoaws-${nextId('x').slice(2)}`) : null,
      access_key_id_masked:
        body.type === 'access_key'
          ? `${body.access_key_id.slice(0, 4)}****${body.access_key_id.slice(-4)}`
          : null,
      remediation_role_arn: body.type === 'role' ? (body.remediation_role_arn ?? null) : null,
      remediation_enabled: body.type === 'role' ? !!body.remediation_role_arn : true,
      last_verified_at: null,
      last_error: null,
      created_at: now(),
    }
    db.connections.push(conn)
    return ok(conn, 'Connection created', 201)
  }),

  http.delete('/api/connections/:id', async ({ params, request }) => {
    const idx = db.connections.findIndex((x) => x.id === params.id)
    if (idx === -1)
      return fail(404, 'CONNECTION_NOT_FOUND', 'Connection not found', pathOf(request))
    db.connections.splice(idx, 1)
    db.conversations = db.conversations.filter((c) => c.connection_id !== params.id)
    return ok(null, 'Connection deleted')
  }),

  http.post('/api/connections/:id/verify', async ({ params, request }) => {
    const c = db.connections.find((x) => x.id === params.id)
    if (!c) return fail(404, 'CONNECTION_NOT_FOUND', 'Connection not found', pathOf(request))
    await delay(1200)
    // Mock rule: names containing "fail" simulate an AssumeRole / auth failure.
    const failed = /fail/i.test(c.name)
    const result: VerifyResult = failed
      ? {
          status: 'failed',
          account_id: null,
          arn: null,
          checked_at: now(),
          error: 'AccessDenied: User is not authorized to perform sts:AssumeRole',
        }
      : {
          status: 'connected',
          account_id: '123456789012',
          arn:
            c.type === 'role'
              ? `arn:aws:sts::123456789012:assumed-role/AutoAWSReadOnly/autoaws-${c.id}`
              : 'arn:aws:iam::123456789012:user/lab',
          checked_at: now(),
          error: null,
        }
    c.status = result.status
    c.account_id = result.account_id
    c.last_verified_at = result.checked_at
    c.last_error = result.error
    return ok(result, failed ? 'Connection verification failed' : 'Connection verified')
  }),

  http.get('/api/connections/:id/cloudformation', async ({ params, request }) => {
    const c = db.connections.find((x) => x.id === params.id)
    if (!c) return fail(404, 'CONNECTION_NOT_FOUND', 'Connection not found', pathOf(request))
    if (c.type !== 'role')
      return fail(
        400,
        'VALIDATION_ERROR',
        'CloudFormation template is only available for role connections',
        pathOf(request),
      )
    const info: CloudFormationInfo = {
      stack_name: 'AutoAWSReadOnlyRole',
      role_name: 'AutoAWSReadOnly',
      external_id: c.external_id ?? '',
      platform_account_id: '111122223333',
      template_yaml: cfnTemplate(c.external_id ?? ''),
    }
    return ok(info)
  }),

  // ---------- conversations ----------
  http.get('/api/conversations', async ({ request }) => {
    const cid = new URL(request.url).searchParams.get('connection_id')
    await delay(120)
    const items = db.conversations
      .filter((c) => !cid || c.connection_id === cid)
      .map(({ messages: _m, ...rest }) => rest)
      .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
    return ok(items)
  }),

  http.get('/api/conversations/:id', async ({ params, request }) => {
    const c = db.conversations.find((x) => x.id === params.id)
    if (!c) return fail(404, 'CONVERSATION_NOT_FOUND', 'Conversation not found', pathOf(request))
    return ok({ ...c, messages: db.messages.get(c.id) ?? [] })
  }),

  http.post('/api/conversations', async ({ request }) => {
    const body = (await request.json()) as CreateConversationInput
    const conn = db.connections.find((x) => x.id === body.connection_id)
    if (!conn) return fail(404, 'CONNECTION_NOT_FOUND', 'Connection not found', pathOf(request))
    if (conn.status !== 'connected')
      return fail(400, 'CONNECTION_NOT_VERIFIED', 'Connection is not verified yet', pathOf(request))
    const conv: Conversation = {
      id: nextId('conv'),
      connection_id: conn.id,
      title: '',
      created_at: now(),
      updated_at: now(),
    }
    db.conversations.push(conv)
    db.messages.set(conv.id, [])
    return ok(conv, 'Conversation created', 201)
  }),

  http.delete('/api/conversations/:id', async ({ params, request }) => {
    const idx = db.conversations.findIndex((x) => x.id === params.id)
    if (idx === -1)
      return fail(404, 'CONVERSATION_NOT_FOUND', 'Conversation not found', pathOf(request))
    db.conversations.splice(idx, 1)
    db.messages.delete(String(params.id))
    return ok(null, 'Conversation deleted')
  }),

  http.post('/api/conversations/:id/messages', async ({ params, request }) => {
    const conv = db.conversations.find((x) => x.id === params.id)
    if (!conv) return fail(404, 'CONVERSATION_NOT_FOUND', 'Conversation not found', pathOf(request))
    const body = (await request.json()) as SendMessageInput
    if (!body.content?.trim())
      return fail(422, 'VALIDATION_ERROR', 'Invalid request: content is required', pathOf(request))
    if (
      db.jobs.some((j) => j.conversation_id === conv.id && ['queued', 'running'].includes(j.status))
    )
      return fail(
        409,
        'JOB_IN_PROGRESS',
        'A diagnosis is already running in this conversation',
        pathOf(request),
      )

    const list = db.messages.get(conv.id) ?? []
    list.push({
      id: nextId('msg'),
      role: 'user',
      content: body.content,
      answer: null,
      tool_calls: [],
      created_at: now(),
    })
    db.messages.set(conv.id, list)
    if (!conv.title) conv.title = body.content.slice(0, 60)
    conv.updated_at = now()

    const job: Job = {
      id: nextId('job'),
      type: 'diagnosis',
      conversation_id: conv.id,
      status: 'queued',
      cancel_requested: false,
      message_id: null,
      error: null,
      events: [],
      created_at: now(),
      updated_at: now(),
    }
    db.jobs.push(job)
    void runMockJob(job, conv, list, body.content)
    return ok({ ...job, events: [] }, 'Diagnosis started', 202)
  }),

  http.get('/api/jobs/:id', async ({ params, request }) => {
    const job = db.jobs.find((x) => x.id === params.id)
    if (!job) return fail(404, 'JOB_NOT_FOUND', 'Job not found', pathOf(request))
    const after = Number(new URL(request.url).searchParams.get('after') ?? -1)
    return ok({ ...job, events: job.events.filter((e) => e.seq > after) })
  }),

  http.post('/api/jobs/:id/cancel', async ({ params, request }) => {
    const job = db.jobs.find((x) => x.id === params.id)
    if (!job) return fail(404, 'JOB_NOT_FOUND', 'Job not found', pathOf(request))
    if (['queued', 'running'].includes(job.status)) job.cancel_requested = true
    return ok(job, 'Cancel requested')
  }),

  // ---------- remediation (human-in-the-loop) ----------
  http.patch('/api/connections/:id', async ({ params, request }) => {
    const c = db.connections.find((x) => x.id === params.id)
    if (!c) return fail(404, 'CONNECTION_NOT_FOUND', 'Connection not found', pathOf(request))
    const body = (await request.json()) as { remediation_role_arn: string | null }
    c.remediation_role_arn = body.remediation_role_arn
    c.remediation_enabled = !!body.remediation_role_arn
    return ok(c, 'Connection updated')
  }),

  http.get('/api/proposals', async ({ request }) => {
    const q = new URL(request.url).searchParams
    const conv = q.get('conversation_id')
    const status = q.get('status')
    return ok(
      db.proposals.filter(
        (p) => (!conv || p.conversation_id === conv) && (!status || p.status === status),
      ),
    )
  }),

  http.get('/api/proposals/:id', async ({ params, request }) => {
    const p = db.proposals.find((x) => x.id === params.id)
    if (!p) return fail(404, 'PROPOSAL_NOT_FOUND', 'Proposal not found', pathOf(request))
    return ok(p)
  }),

  http.post('/api/proposals/:id/decision', async ({ params, request }) => {
    const p = db.proposals.find((x) => x.id === params.id)
    if (!p) return fail(404, 'PROPOSAL_NOT_FOUND', 'Proposal not found', pathOf(request))
    if (p.status !== 'PENDING_APPROVAL')
      return fail(
        409,
        'PROPOSAL_NOT_PENDING',
        `Proposal is not waiting for a decision (${p.status})`,
        pathOf(request),
      )
    const body = (await request.json()) as { decision: string; feedback?: string }
    const mark = (status: Proposal['status'], note: string) => {
      p.status = status
      p.history = [...p.history, { status, at: now(), note }]
      p.updated_at = now()
    }
    if (body.decision === 'approve') {
      mark('APPROVED', 'approved by the user')
      setTimeout(() => mark('EXECUTING', 're-checking the resource'), 600)
      setTimeout(() => {
        p.verification = {
          ok: true,
          details: 'subnet-0a1b uses rtb-public: 0.0.0.0/0 -> igw-0f3c (active)',
        }
        mark('SUCCEEDED', 'verified')
      }, 2000)
      return ok({ proposal: p, followup_question: null }, 'Proposal approved')
    }
    if (body.decision === 'reject') {
      mark('REJECTED', 'rejected by the user')
      return ok({ proposal: p, followup_question: null }, 'Proposal rejected')
    }
    mark('SUPERSEDED', `feedback: ${body.feedback ?? ''}`)
    return ok(
      {
        proposal: p,
        followup_question: `Góp ý cho đề xuất (${p.id}): ${body.feedback ?? ''}\nHãy đề xuất lại.`,
      },
      'Feedback sent',
    )
  }),

  http.get('/api/remediation/actions', async () => ok([])),

  // ---------- tools ----------
  http.get('/api/tools', async () => {
    await delay(100)
    return ok(tools)
  }),
]

function cfnTemplate(externalId: string): string {
  return `AWSTemplateFormatVersion: '2010-09-09'
Description: AutoAWS read-only role (mock template)
Resources:
  AutoAWSReadOnly:
    Type: AWS::IAM::Role
    Properties:
      RoleName: AutoAWSReadOnly
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              AWS: arn:aws:iam::111122223333:root
            Action: sts:AssumeRole
            Condition:
              StringEquals:
                sts:ExternalId: ${externalId}
      Policies:
        - PolicyName: AutoAWSReadOnly
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - ec2:Describe*
                  - elasticloadbalancing:Describe*
                  - route53:List*
                  - ssm:DescribeInstanceInformation
                  - cloudwatch:GetMetricData
                  - logs:StartQuery
                  - logs:GetQueryResults
                  - cloudtrail:LookupEvents
                Resource: '*'
              - Effect: Deny
                Action:
                  - s3:GetObject
                  - secretsmanager:*
                  - ssm:GetParameter*
                  - kms:Decrypt
                Resource: '*'
Outputs:
  RoleArn:
    Value: !GetAtt AutoAWSReadOnly.Arn
`
}

/** KB1 answers carry one proposal (associate_route_table) stored in the mock db. */
function withMockProposals(answer: DiagnosisAnswer, conversationId: string, messageId: string) {
  if (!answer.fix_steps.some((f) => f.includes('subnet-0a1b'))) return answer
  const p: Proposal = {
    id: nextId('prop'),
    conversation_id: conversationId,
    message_id: messageId,
    connection_id: db.connections[0]?.id ?? '',
    kind: 'fix',
    parent_id: null,
    action: 'associate_route_table',
    params: { subnet_id: 'subnet-0a1b', route_table_id: 'rtb-public' },
    reason: 'Gắn subnet-0a1b về route table public có tuyến 0.0.0.0/0 → igw-0f3c.',
    status: 'PENDING_APPROVAL',
    preview: {
      summary: 'Associate subnet-0a1b with route table rtb-public',
      changes: [
        {
          field: 'Route table of subnet-0a1b',
          before: 'rtb-07c9: 10.0.0.0/16 -> local (active)',
          after: 'rtb-public: 0.0.0.0/0 -> igw-0f3c (active), 10.0.0.0/16 -> local (active)',
        },
      ],
      impact: 'Every instance in subnet-0a1b uses the routes of rtb-public.',
      risk: 'low',
      rollback: 'Associate subnet-0a1b back with rtb-07c9',
      verify: 'The effective route table of subnet-0a1b has 0.0.0.0/0 to an Internet gateway.',
    },
    result: null,
    verification: null,
    error: null,
    history: [{ status: 'PENDING_APPROVAL', at: now(), note: 'proposed by the agent' }],
    created_at: now(),
    updated_at: now(),
    expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
  }
  db.proposals.unshift(p)
  return {
    ...answer,
    proposals: [
      { action: p.action, params: p.params, reason: p.reason, proposal_id: p.id, error: null },
    ],
  }
}

/** Plays a scripted scenario into the job, like the agent-worker would. */
async function runMockJob(job: Job, conv: Conversation, list: Message[], question: string) {
  const scenario = pickScenario(question)
  const messageId = nextId('msg')
  const toolCalls = new Map<string, ToolCall>()
  job.status = 'running'
  const emit = (event: AgentEvent) => {
    job.events.push({ ...event, seq: job.events.length } as Job['events'][number])
    job.updated_at = now()
  }
  for (const { delay: ms, event } of scenarioEvents(scenario, messageId)) {
    await new Promise((r) => setTimeout(r, ms))
    if (job.cancel_requested) {
      list.push({
        id: nextId('msg'),
        role: 'assistant',
        content: STOPPED_NOTE,
        answer: null,
        tool_calls: Array.from(toolCalls.values()),
        created_at: now(),
      })
      emit({ type: 'error', data: { error: 'CANCELLED', message: 'Stopped by the user' } })
      emit({ type: 'done', data: {} })
      job.status = 'cancelled'
      return
    }
    if (event.type === 'tool_call') {
      toolCalls.set(event.data.id, {
        id: event.data.id,
        tool: event.data.tool,
        input: event.data.input,
        output_summary: '',
        status: 'ok',
        error: null,
        duration_ms: 0,
      })
    } else if (event.type === 'tool_result') {
      const tc = toolCalls.get(event.data.id)
      if (tc) {
        tc.output_summary = event.data.output_summary
        tc.status = event.data.status
        tc.duration_ms = event.data.duration_ms
      }
    } else if (event.type === 'answer') {
      event.data.answer = withMockProposals(event.data.answer, conv.id, messageId)
      list.push({
        id: messageId,
        role: 'assistant',
        content: event.data.content,
        answer: event.data.answer,
        tool_calls: Array.from(toolCalls.values()),
        created_at: now(),
      })
      conv.updated_at = now()
      job.message_id = messageId
    }
    emit(event)
  }
  job.status = 'succeeded'
}
