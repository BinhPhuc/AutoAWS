# AutoAWS — API Contract (FE ↔ BE)

> Hợp đồng dùng chung để frontend và backend làm **song song**. Mọi thay đổi endpoint/schema phải sửa file này trước, rồi mới sửa code hai phía.
> Base URL dev: `http://localhost:8000`. Mọi endpoint có tiền tố `/api`. JSON, UTF-8. Thời gian ISO-8601 UTC.
> Bản init **không có auth**; sau này thêm header `Authorization: Bearer <JWT>` không đổi payload.
> **Ngôn ngữ:** `message`, status SSE, label/mô tả tool, UI → **tiếng Anh**. Riêng **câu trả lời của agent** (`DiagnosisAnswer` và `content` của assistant) → **tiếng Việt**. Tài liệu này tiếng Việt.

## 0. Quy ước response (áp dụng cho MỌI endpoint JSON)

### Thành công — luôn là envelope
```json
{
  "status_code": 200,
  "message": "OK",
  "data": <generic>        // object | array | null — nội dung thực; schema ghi ở từng endpoint
}
```
- `status_code` trùng HTTP status (200, 201).
- `message` ngắn, tiếng Anh, dùng được để hiện toast (ví dụ `"Connection created"`). Mặc định `"OK"`.
- `data` là **phần duy nhất** FE dùng cho logic; `client.ts` bóc `data` và trả về cho hooks.
- Danh sách: `data` là **array** trực tiếp (không bọc `items`).
- Xoá thành công: `200`, `data: null`.

### Lỗi — luôn là
```json
{
  "status_code": 404,
  "message": "Connection not found",            // thông điệp cho người dùng (tiếng Anh)
  "error": "CONNECTION_NOT_FOUND",              // mã lỗi ổn định cho FE rẽ nhánh
  "path": "/api/connections/conn_01HX",
  "timestamp": "2026-10-16T03:00:00Z"
}
```
Không có trường `data` trong response lỗi. HTTP status = `status_code`.

| `error` | HTTP | `message` mẫu | Khi nào |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | `"Invalid request: <field> <reason>"` | Body/query sai schema |
| `CONNECTION_NOT_FOUND` | 404 | `"Connection not found"` | |
| `CONVERSATION_NOT_FOUND` | 404 | `"Conversation not found"` | |
| `CONNECTION_NOT_VERIFIED` | 400 | `"Connection is not verified yet"` | Tạo hội thoại / gửi câu hỏi trên connection chưa `connected` |
| `AWS_AUTH_FAILED` | 400 | `"AWS authentication failed: <reason>"` | Credentials sai, AssumeRole bị từ chối |
| `AWS_ACCESS_DENIED` | 403 | `"AWS access denied: <action>"` | Role thiếu quyền cho một lệnh đọc |
| `LLM_UNAVAILABLE` | 503 | `"LLM provider is unavailable"` | Provider lỗi / chưa cấu hình / không có MCP client trả lời kịp (`LLM_PROVIDER=mcp`) |
| `MAX_ITERATIONS` | — | `"Stopped after 8 reasoning steps without a conclusion"` | **Chỉ qua SSE `error`**: agent hết số vòng mà chưa kết luận |
| `NOT_FOUND` | 404 | `"Not Found"` | Route không tồn tại |
| `METHOD_NOT_ALLOWED` | 405 | `"Method Not Allowed"` | Sai HTTP method |
| `NOT_IMPLEMENTED` | 501 | `"Checklist runs are not available yet"` | Tính năng chưa có (checklist) |
| `INTERNAL` | 500 | `"Internal server error"` | Lỗi không lường trước |

### Ngoại lệ: SSE stream
`POST /api/conversations/{id}/messages` trả `text/event-stream`, **không** dùng envelope. Lỗi **trước khi** stream bắt đầu (404, 400…) vẫn trả JSON lỗi theo quy ước trên; lỗi **trong lúc** stream gửi bằng event `error` (mục 3).

---

## 1. Health

### `GET /api/health`
```json
200 { "status_code": 200, "message": "OK",
      "data": { "status": "ok", "version": "0.1.0", "llm_provider": "mock" } }
```
`llm_provider` ∈ `mock | anthropic | bedrock | mcp` (`mcp` = một MCP client đóng vai LLM, xem mục 6).

---

## 2. Connections — kết nối tài khoản AWS

### Schema `Connection`
```json
{
  "id": "conn_01HX...",
  "name": "Lab account",
  "type": "access_key" | "role",
  "region": "ap-southeast-1",
  "status": "pending" | "connected" | "failed",
  "account_id": "123456789012" | null,
  "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly" | null,
  "external_id": "autoaws-7f3a..." | null,
  "access_key_id_masked": "AKIA****XYZ1" | null,
  "last_verified_at": "2026-10-16T03:00:00Z" | null,
  "last_error": "..." | null,
  "created_at": "2026-10-16T02:58:00Z"
}
```
Secret key **không bao giờ** trả về client.

### `POST /api/connections`
Tạo kết nối. Hai dạng body (phân biệt bằng `type`):
```json
{ "type": "access_key", "name": "Lab account", "region": "ap-southeast-1",
  "access_key_id": "AKIA...", "secret_access_key": "..." }
```
```json
{ "type": "role", "name": "Prod", "region": "ap-southeast-1",
  "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
  "external_id": "autoaws-7f3a..." }
```
`external_id` với `type=role`: nếu bỏ trống, server tự sinh và trả về (client hiển thị để người dùng đưa vào CloudFormation).
```json
201 { "status_code": 201, "message": "Connection created", "data": Connection }   // status "pending"
```

### `GET /api/connections`
```json
200 { "status_code": 200, "message": "OK", "data": [Connection] }
```
### `GET /api/connections/{id}`
```json
200 { "status_code": 200, "message": "OK", "data": Connection }
```
### `DELETE /api/connections/{id}`
```json
200 { "status_code": 200, "message": "Connection deleted", "data": null }
```

### `POST /api/connections/{id}/verify`
Server lấy credentials (trực tiếp hoặc `AssumeRole`), gọi `sts:GetCallerIdentity` + `ec2:DescribeRegions` (hai action này luôn có trong policy của template CloudFormation). Luôn `200` (kết quả verify nằm trong `data`, không phải lỗi HTTP) và cập nhật `status` của Connection.
```json
200 { "status_code": 200, "message": "Connection verified",
      "data": { "status": "connected", "account_id": "123456789012",
                "arn": "arn:aws:sts::123456789012:assumed-role/AutoAWSReadOnly/autoaws-conn_01HX",
                "checked_at": "2026-10-16T03:00:00Z", "error": null } }

200 { "status_code": 200, "message": "Connection verification failed",
      "data": { "status": "failed", "account_id": null, "arn": null,
                "checked_at": "2026-10-16T03:00:00Z", "error": "AccessDenied: User is not authorized to perform sts:AssumeRole" } }
```

### `GET /api/connections/{id}/cloudformation`
Chỉ với `type=role` (với `access_key` → `400 VALIDATION_ERROR`). Template YAML tạo IAM role chỉ đọc có trust policy tới tài khoản nền tảng + `sts:ExternalId` = `external_id` của connection.
```json
200 { "status_code": 200, "message": "OK",
      "data": { "stack_name": "AutoAWSReadOnlyRole",
                "role_name": "AutoAWSReadOnly",
                "external_id": "autoaws-7f3a...",
                "platform_account_id": "111122223333",
                "template_yaml": "AWSTemplateFormatVersion: '2010-09-09'\n..." } }
```
Client hiển thị nút copy `template_yaml` + hướng dẫn tạo stack (link "Launch Stack" sau).

---

## 3. Conversations — hội thoại chẩn đoán

### Schema
```json
Conversation {
  "id": "conv_01HX...", "connection_id": "conn_...", "title": "Không SSH được vào web-server",   // tự đặt từ câu hỏi đầu
  "created_at": "...", "updated_at": "...",
  "messages": [Message]            // chỉ có ở GET /conversations/{id}
}

Message {
  "id": "msg_...", "role": "user" | "assistant",
  "content": "text",                // user: câu hỏi; assistant: tóm tắt 1 đoạn (tiếng Việt)
  "answer": DiagnosisAnswer | null, // assistant: câu trả lời có cấu trúc
  "tool_calls": [ToolCall],         // assistant: các lần gọi công cụ dẫn tới câu trả lời
  "created_at": "..."
}

ToolCall {
  "id": "tc_...", "tool": "describe_security_groups",
  "input": { "group_ids": ["sg-0d4e..."] },
  "output_summary": "1 security group; inbound: 22/tcp from 0.0.0.0/0",   // đã rút gọn + sanitize
  "status": "ok" | "error", "error": null, "duration_ms": 412
}

DiagnosisAnswer {
  "summary": "Subnet không có đường ra Internet; Security Group không phải nguyên nhân.",
  "cause": "Route table rtb-07c9 gắn với subnet subnet-0a1b không có tuyến 0.0.0.0/0 tới Internet Gateway.",
  "evidence": [
    { "text": "rtb-07c9 chỉ có tuyến local 10.0.0.0/16", "source": "describe_route_tables", "verified": true },
    { "text": "ReplaceRouteTableAssociation lúc 09:14 ngày 09/10/2026 bởi user dev-tuan", "source": "cloudtrail_lookup_events", "verified": true }
  ],
  "fix_steps": [
    "Gắn lại subnet-0a1b vào route table public, hoặc",
    "Thêm tuyến 0.0.0.0/0 → igw-xxxx vào rtb-07c9",
    "Tạm thời: truy cập qua Session Manager (SSM Agent đang Online)"
  ],
  "unverified": [
    { "text": "sshd có đang chạy trong máy không", "how_to_check": "sudo systemctl status sshd" }
  ],
  "confidence": "high" | "medium" | "low"
}
```
Mọi chuỗi văn xuôi trong `DiagnosisAnswer` là **tiếng Việt** (system prompt ép model trả lời tiếng Việt); tên tài nguyên, lệnh, mã lỗi AWS giữ nguyên gốc.

### `POST /api/conversations`
```json
{ "connection_id": "conn_..." }
→ 201 { "status_code": 201, "message": "Conversation created", "data": Conversation }   // không messages
```
Connection chưa `connected` → `400 CONNECTION_NOT_VERIFIED`.

### `GET /api/conversations`
```json
200 { "status_code": 200, "message": "OK", "data": [Conversation] }   // không messages
```
Query tuỳ chọn: `?connection_id=conn_...` để lọc.

### `GET /api/conversations/{id}`
```json
200 { "status_code": 200, "message": "OK", "data": Conversation }     // kèm messages
```
### `DELETE /api/conversations/{id}`
```json
200 { "status_code": 200, "message": "Conversation deleted", "data": null }
```

### `POST /api/conversations/{id}/messages` — **streaming SSE** (ngoại lệ của envelope)
Request:
```json
{ "content": "Tôi không SSH được vào instance web-server, Security Group đã mở port 22 rồi." }
```
Response: `200`, `Content-Type: text/event-stream`. Mỗi event dạng:
```
event: <type>
data: <JSON một dòng>

```
Thứ tự điển hình: `status` → (`tool_call` → `tool_result`)* → `answer` → `done`. Lỗi: `error` rồi `done`.

| event | data | Ý nghĩa |
|---|---|---|
| `status` | `{ "text": "Planning checks…" }` | Trạng thái để hiển thị dòng "…ing" (`"Reading security groups…"`, `"Analyzing results…"`) |
| `tool_call` | `{ "id": "tc_1", "tool": "describe_instances", "input": {...} }` | Agent gọi công cụ |
| `tool_result` | `{ "id": "tc_1", "status": "ok", "output_summary": "...", "duration_ms": 300 }` | Kết quả rút gọn |
| `answer` | `{ "message_id": "msg_...", "content": "...", "answer": DiagnosisAnswer }` | Câu trả lời cuối |
| `error` | `{ "error": "LLM_UNAVAILABLE", "message": "LLM provider is unavailable" }` | Lỗi trong lúc stream (cùng tên trường với JSON lỗi) |
| `done` | `{}` | Kết thúc stream |

Lỗi trước khi stream bắt đầu (hội thoại không tồn tại, connection chưa verify, body sai) → JSON lỗi theo mục 0, không phải SSE.
Client dùng `fetch` + `ReadableStream` (vì là POST). Khi stream kết thúc, `GET /api/conversations/{id}` phải trả về đúng message vừa stream (server lưu trước khi gửi `done`).

**Lượt không có kết luận vẫn được lưu.** Khi stream đã bắt đầu (server đã lưu câu hỏi) mà lượt kết thúc không có `answer` (event `error`, hết vòng, hoặc client ngắt kết nối / bấm Stop), server lưu một message assistant với `answer: null`, `content` là câu giải thích tiếng Việt (ví dụ `"Chưa hoàn thành chẩn đoán: LLM provider is unavailable"`, `"Lượt chẩn đoán đã bị dừng trước khi có kết luận."`) và `tool_calls` gồm các công cụ đã chạy. Nhờ vậy lịch sử luôn xen kẽ user/assistant. Client ngắt kết nối = dừng agent.

---

## 4. Tools — danh sách công cụ đọc AWS

### `GET /api/tools`
```json
200 { "status_code": 200, "message": "OK", "data": [
  { "name": "describe_instances", "group": "compute",
    "label": "EC2 instances",
    "description": "State, IPs, subnet and security groups of EC2 instances",
    "input_schema": { "type": "object", "properties": { "instance_ids": {...}, "name_tag": {...} } },
    "aws_actions": ["ec2:DescribeInstances"] }
]}
```
`group` ∈ `compute | network | dns | elb | metrics | logs | cloudtrail`. `label` là nhãn ngắn để UI hiển thị trong timeline; `description` là mô tả đưa cho LLM và tooltip.

---

## 5. Checklists — **ngoài phạm vi init**
Dự kiến: `POST /api/checklists/runs`, `GET /api/checklists/runs/{id}` (kết quả từng mục stream hoặc poll). Router để trống.

---

## 6. MCP bridge — MCP client đóng vai LLM (chỉ dev/test)

Chỉ bật khi `LLM_PROVIDER=mcp`. Dùng khi chưa có quyền gọi Bedrock/Anthropic: mỗi lượt `provider.chat()` của agent được xếp hàng, một MCP client (ví dụ Claude Code) lấy về, suy luận và trả lời. Vòng lặp agent, công cụ, sanitizer, SSE giữ nguyên. **Không phải endpoint cho FE**, không theo envelope (giao thức MCP).

- Endpoint: `http://localhost:8000/mcp/` (MCP Streamable HTTP; có dấu `/` cuối). Kết nối Claude Code: `claude mcp add --transport http autoaws-llm http://localhost:8000/mcp/`.
- Không có auth → chỉ chạy trên máy dev (bind `127.0.0.1`).
- Request chờ quá `MCP_BRIDGE_TIMEOUT_SECONDS` (mặc định 900) → agent nhận lỗi `LLM_UNAVAILABLE`.

| MCP tool | Tham số | Trả về |
|---|---|---|
| `next_llm_request` | `wait_seconds` (0–60, mặc định 30), `include_system` (mặc định `true`), `include_tools` (mặc định `true`) | Lượt cũ nhất đang chờ: `{ "pending": true, "request_id", "created_at", "system", "messages": [LLMMessage], "tools": [{name, description, input_schema}] }`; hết thời gian chờ mà không có lượt nào → `{ "pending": false }` |
| `respond_llm_request` | `request_id`, **một trong hai**: `tool_calls: [{ "name", "input" }]` (muốn đọc thêm dữ liệu) hoặc `text` (câu trả lời cuối = JSON `DiagnosisAnswer`, mục 3) | `{ "ok": true }`; tên tool không có trong `tools`, request không tồn tại / đã trả lời → lỗi MCP (`isError`) |
| `list_llm_requests` | — | `{ "requests": [{ "request_id", "created_at", "last_user_message" }] }` các lượt đang chờ |

`LLMMessage` = `{ "role": "user" | "assistant" | "tool", "content", "tool_calls"?: [{id, name, input}], "tool_call_id"?, "tool_name"? }` (`content` của `tool` là JSON kết quả công cụ đã sanitize).

---

## Danh sách công cụ bản init (tên ổn định; `label` do backend trả về, FE không tự đặt)

| name | group | label | AWS action |
|---|---|---|---|
| `get_caller_identity` | compute | Caller identity | sts:GetCallerIdentity |
| `describe_instances` | compute | EC2 instances | ec2:DescribeInstances |
| `describe_instance_status` | compute | Instance status checks | ec2:DescribeInstanceStatus |
| `ssm_describe_instance_information` | compute | SSM Agent status | ssm:DescribeInstanceInformation |
| `describe_security_groups` | network | Security groups | ec2:DescribeSecurityGroups |
| `describe_network_acls` | network | Network ACLs | ec2:DescribeNetworkAcls |
| `describe_route_tables` | network | Route tables | ec2:DescribeRouteTables, DescribeSubnets |
| `describe_subnets` | network | Subnets | ec2:DescribeSubnets |
| `describe_internet_gateways` | network | Internet gateways | ec2:DescribeInternetGateways |
| `route53_list_records` | dns | Route 53 records | route53:ListHostedZones, ListResourceRecordSets |
| `resolve_dns_public` | dns | Public DNS lookup | (không cần AWS) truy vấn DNS công khai (`DNS_RESOLVERS`, mặc định 8.8.8.8, 1.1.1.1) |
| `elbv2_describe_load_balancers` | elb | Load balancers | elasticloadbalancing:DescribeLoadBalancers, DescribeListeners |
| `elbv2_describe_target_health` | elb | Target health | elasticloadbalancing:DescribeTargetGroups, DescribeTargetHealth |
| `cloudwatch_get_metric_data` | metrics | CloudWatch metrics | cloudwatch:GetMetricData — *stub, M3* |
| `logs_insights_query` | logs | CloudWatch Logs query | logs:StartQuery, GetQueryResults — *stub, M3* |
| `cloudtrail_lookup_events` | cloudtrail | CloudTrail events | cloudtrail:LookupEvents — *stub, M3* |
