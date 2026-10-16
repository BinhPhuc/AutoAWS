import type { AgentEvent, DiagnosisAnswer } from '@/api/types'

/**
 * Scripted SSE sequences for the three reference scenarios (KB1–KB3 in docs/SYSTEM_OVERVIEW.md).
 * Status text: English. Diagnosis content: Vietnamese (matches backend contract).
 */

interface Step {
  tool: string
  input: Record<string, unknown>
  output: string
  ms: number
}

export interface Scenario {
  match: (q: string) => boolean
  steps: Step[]
  answer: DiagnosisAnswer
  content: string
}

const kb1: Scenario = {
  match: (q) => /ssh|port 22|web-server/i.test(q),
  steps: [
    {
      tool: 'describe_instances',
      input: { name_tag: 'web-server' },
      output:
        'i-0abc1234 web-server: running, public IP 54.169.10.20, subnet subnet-0a1b, SG sg-0d4e',
      ms: 420,
    },
    {
      tool: 'describe_instance_status',
      input: { instance_ids: ['i-0abc1234'] },
      output: '2/2 status checks passed',
      ms: 310,
    },
    {
      tool: 'describe_security_groups',
      input: { group_ids: ['sg-0d4e'] },
      output: '1 security group; inbound: 22/tcp from 0.0.0.0/0, 80/tcp from 0.0.0.0/0',
      ms: 280,
    },
    {
      tool: 'describe_route_tables',
      input: { subnet_id: 'subnet-0a1b' },
      output: 'rtb-07c9: 1 route (10.0.0.0/16 → local). No 0.0.0.0/0 route.',
      ms: 350,
    },
    {
      tool: 'ssm_describe_instance_information',
      input: { instance_ids: ['i-0abc1234'] },
      output: 'SSM Agent: Online (last ping 2 min ago)',
      ms: 260,
    },
    {
      tool: 'cloudtrail_lookup_events',
      input: { resource_name: 'subnet-0a1b', hours: 72 },
      output: 'ReplaceRouteTableAssociation 2026-10-09T09:14Z by dev-tuan (rtb-public → rtb-07c9)',
      ms: 900,
    },
  ],
  content: 'Subnet không có đường ra Internet; Security Group không phải nguyên nhân.',
  answer: {
    summary: 'Subnet không có đường ra Internet; Security Group không phải nguyên nhân.',
    cause:
      'Route table rtb-07c9 gắn với subnet subnet-0a1b không có tuyến 0.0.0.0/0 tới Internet Gateway, nên gói tin SSH từ ngoài không tới được instance dù SG đã mở port 22.',
    evidence: [
      {
        text: 'Instance i-0abc1234 đang running, 2/2 status check đạt, public IP 54.169.10.20',
        source: 'describe_instances',
        verified: true,
      },
      {
        text: 'Security Group sg-0d4e cho phép TCP/22 từ 0.0.0.0/0',
        source: 'describe_security_groups',
        verified: true,
      },
      {
        text: 'rtb-07c9 chỉ có tuyến local 10.0.0.0/16, không có tuyến tới igw',
        source: 'describe_route_tables',
        verified: true,
      },
      {
        text: 'ReplaceRouteTableAssociation lúc 09:14 ngày 09/10/2026 bởi user dev-tuan',
        source: 'cloudtrail_lookup_events',
        verified: true,
      },
    ],
    fix_steps: [
      'Gắn lại subnet-0a1b vào route table public (rtb-public), hoặc',
      'Thêm tuyến 0.0.0.0/0 → igw-xxxx vào rtb-07c9',
      'Tạm thời: truy cập qua Session Manager vì SSM Agent đang Online',
    ],
    unverified: [
      { text: 'sshd có đang chạy trong máy không', how_to_check: 'sudo systemctl status sshd' },
    ],
    confidence: 'high',
  },
}

const kb2: Scenario = {
  match: (q) => /dns|domain|tên miền|8080|docker|example\.com/i.test(q),
  steps: [
    {
      tool: 'resolve_dns_public',
      input: { hostname: 'app.example.com' },
      output: 'A 13.212.44.10 (TTL 300)',
      ms: 180,
    },
    {
      tool: 'route53_list_records',
      input: { name: 'app.example.com' },
      output: 'app.example.com A → 13.212.44.10',
      ms: 400,
    },
    {
      tool: 'describe_instances',
      input: { name_tag: 'app' },
      output: 'i-0def5678 app: running, public IP 54.169.88.2 (dynamic), SG sg-0d4e',
      ms: 390,
    },
    {
      tool: 'describe_security_groups',
      input: { group_ids: ['sg-0d4e'] },
      output: 'inbound: 22/tcp, 80/tcp. No rule for 8080.',
      ms: 270,
    },
    {
      tool: 'cloudtrail_lookup_events',
      input: { resource_name: 'i-0def5678', hours: 48 },
      output: 'StopInstances 2026-10-15T20:02Z, StartInstances 2026-10-15T20:10Z by admin',
      ms: 820,
    },
  ],
  content: 'Hai vấn đề: bản ghi DNS trỏ tới IP cũ và Security Group chưa mở port 8080.',
  answer: {
    summary: 'Hai vấn đề: bản ghi DNS trỏ tới IP cũ và Security Group chưa mở port 8080.',
    cause:
      'Instance bị stop/start hôm qua nên public IP động đã đổi từ 13.212.44.10 sang 54.169.88.2, nhưng bản ghi A vẫn trỏ IP cũ. Ngoài ra sg-0d4e chưa cho phép TCP/8080.',
    evidence: [
      {
        text: 'app.example.com phân giải về 13.212.44.10',
        source: 'resolve_dns_public',
        verified: true,
      },
      {
        text: 'Public IP hiện tại của i-0def5678 là 54.169.88.2',
        source: 'describe_instances',
        verified: true,
      },
      {
        text: 'StopInstances / StartInstances lúc 20:02–20:10 ngày 15/10 bởi admin',
        source: 'cloudtrail_lookup_events',
        verified: true,
      },
      {
        text: 'sg-0d4e không có rule inbound cho port 8080',
        source: 'describe_security_groups',
        verified: true,
      },
    ],
    fix_steps: [
      'Gắn Elastic IP cho instance để IP không đổi khi stop/start',
      'Cập nhật bản ghi A app.example.com về IP mới (hoặc Elastic IP)',
      'Mở inbound TCP/8080 trong sg-0d4e (chỉ từ dải IP cần thiết)',
    ],
    unverified: [
      {
        text: 'Container có đang chạy và map đúng port 8080 không',
        how_to_check: 'docker ps && ss -tlnp | grep 8080',
      },
    ],
    confidence: 'high',
  },
}

const kb3: Scenario = {
  match: (q) => /502|5xx|bad gateway|load balancer|health/i.test(q),
  steps: [
    {
      tool: 'elbv2_describe_load_balancers',
      input: {},
      output: 'alb-web (application), listener 443 → tg-web',
      ms: 450,
    },
    {
      tool: 'cloudwatch_get_metric_data',
      input: { metric: 'HTTPCode_ELB_5XX_Count', hours: 6 },
      output: '5xx: 0 until 14:04, then 120–140/min from 14:05',
      ms: 700,
    },
    {
      tool: 'elbv2_describe_target_health',
      input: { target_group: 'tg-web' },
      output: '2/2 targets unhealthy: Target.ResponseCodeMismatch (health check /health → 404)',
      ms: 380,
    },
    {
      tool: 'logs_insights_query',
      input: { log_group: '/app/web', hours: 2 },
      output: '14:03 "Starting v2.4.0", GET /health 404 ×240, GET /api/health 200 ×240',
      ms: 1200,
    },
    {
      tool: 'cloudtrail_lookup_events',
      input: { hours: 6 },
      output: 'UpdateService (ECS) 2026-10-16T14:03Z by deploy-bot; no changes to tg-web',
      ms: 650,
    },
  ],
  content:
    'Phiên bản mới đổi đường dẫn health check thành /api/health, target group vẫn kiểm tra /health.',
  answer: {
    summary:
      'Phiên bản mới đổi đường dẫn health check thành /api/health, target group vẫn kiểm tra /health nên mọi target bị đánh dấu unhealthy.',
    cause:
      'Lượt triển khai lúc 14:03 đưa phiên bản v2.4.0 lên, phiên bản này không còn phục vụ /health (trả 404). Target group tg-web vẫn health check /health, do đó Load Balancer coi 2/2 target là unhealthy và trả 502.',
    evidence: [
      {
        text: 'HTTPCode_ELB_5XX_Count tăng đột biến từ 14:05',
        source: 'cloudwatch_get_metric_data',
        verified: true,
      },
      {
        text: '2/2 target unhealthy, lý do Target.ResponseCodeMismatch (/health → 404)',
        source: 'elbv2_describe_target_health',
        verified: true,
      },
      {
        text: 'Log ứng dụng: GET /health 404, GET /api/health 200 sau 14:03',
        source: 'logs_insights_query',
        verified: true,
      },
      {
        text: 'UpdateService lúc 14:03 bởi deploy-bot; cấu hình target group không đổi',
        source: 'cloudtrail_lookup_events',
        verified: true,
      },
    ],
    fix_steps: [
      'Cập nhật health check path của tg-web thành /api/health, hoặc',
      'Bổ sung lại route /health trong ứng dụng rồi triển khai lại',
    ],
    unverified: [],
    confidence: 'high',
  },
}

const fallback: Scenario = {
  match: () => true,
  steps: [
    {
      tool: 'get_caller_identity',
      input: {},
      output: 'Account 123456789012, arn:aws:iam::123456789012:user/lab',
      ms: 200,
    },
    { tool: 'describe_instances', input: {}, output: '3 instances: 2 running, 1 stopped', ms: 500 },
  ],
  content: 'Chưa đủ thông tin để kết luận. Hãy mô tả rõ hơn tài nguyên và triệu chứng.',
  answer: {
    summary: 'Chưa đủ thông tin để kết luận.',
    cause:
      'Câu hỏi chưa nêu tài nguyên cụ thể (instance, tên miền, load balancer) hoặc triệu chứng (mã lỗi, thời điểm) nên agent chưa khoanh vùng được.',
    evidence: [
      {
        text: 'Tài khoản 123456789012 có 3 instance (2 running, 1 stopped)',
        source: 'describe_instances',
        verified: true,
      },
    ],
    fix_steps: ['Mô tả lại sự cố kèm tên tài nguyên, mã lỗi và thời điểm bắt đầu'],
    unverified: [
      {
        text: 'Triệu chứng thực tế người dùng gặp',
        how_to_check: 'Thử lại thao tác và ghi lại thông báo lỗi',
      },
    ],
    confidence: 'low',
  },
}

export const scenarios = [kb1, kb2, kb3, fallback]

export function pickScenario(question: string): Scenario {
  return scenarios.find((s) => s.match(question)) ?? fallback
}

/** Converts a scenario into a timed list of events (delay before each event, in ms). */
export function scenarioEvents(
  s: Scenario,
  messageId: string,
): Array<{ delay: number; event: AgentEvent }> {
  const out: Array<{ delay: number; event: AgentEvent }> = []
  out.push({ delay: 300, event: { type: 'status', data: { text: 'Planning checks…' } } })
  s.steps.forEach((step, i) => {
    const id = `tc_${i + 1}`
    out.push({
      delay: 250,
      event: { type: 'status', data: { text: `Reading ${labelOf(step.tool)}…` } },
    })
    out.push({
      delay: 50,
      event: { type: 'tool_call', data: { id, tool: step.tool, input: step.input } },
    })
    out.push({
      delay: step.ms,
      event: {
        type: 'tool_result',
        data: { id, status: 'ok', output_summary: step.output, duration_ms: step.ms },
      },
    })
  })
  out.push({ delay: 300, event: { type: 'status', data: { text: 'Analyzing results…' } } })
  out.push({
    delay: 900,
    event: {
      type: 'answer',
      data: { message_id: messageId, content: s.content, answer: s.answer },
    },
  })
  out.push({ delay: 50, event: { type: 'done', data: {} } })
  return out
}

function labelOf(tool: string): string {
  return tool
    .replace(
      /^(describe_|elbv2_describe_|ssm_describe_|route53_|cloudwatch_get_|logs_|cloudtrail_)/,
      '',
    )
    .replace(/_/g, ' ')
}
