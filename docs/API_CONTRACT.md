# AutoAWS — API Contract (FE ↔ BE)

> Hợp đồng dùng chung để frontend và backend làm **song song**. Mọi thay đổi endpoint/schema phải sửa file này trước, rồi mới sửa code hai phía.
> Base URL dev: `http://localhost:8000`. Mọi endpoint có tiền tố `/api`. JSON, UTF-8. Thời gian ISO-8601 UTC.
> **Xác thực:** xem mục 0.1 — `AUTH_MODE=none` (dev, một người dùng) hoặc `cognito` (Bearer JWT của Cognito). Payload không đổi giữa hai chế độ.
> **Ngôn ngữ:** `message`, event `status` của job, label/mô tả tool, UI → **tiếng Anh**. Riêng **câu trả lời của agent** (`DiagnosisAnswer` và `content` của assistant) → **tiếng Việt**. Tài liệu này tiếng Việt.

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
| `UNAUTHORIZED` | 401 | `"Sign in required"` / `"Invalid or expired token"` | `AUTH_MODE=cognito`: thiếu / sai / hết hạn access token (mục 0.1) |
| `VALIDATION_ERROR` | 422 | `"Invalid request: <field> <reason>"` | Body/query sai schema |
| `CONNECTION_NOT_FOUND` | 404 | `"Connection not found"` | |
| `CONNECTION_SETUP_UNAVAILABLE` | 503 | `"Connection setup is temporarily unavailable"` | Preview template khi thiếu account nền tảng hợp lệ |
| `CONVERSATION_NOT_FOUND` | 404 | `"Conversation not found"` | |
| `CONNECTION_NOT_VERIFIED` | 400 | `"Connection is not verified yet"` | Tạo hội thoại / gửi câu hỏi trên connection chưa `connected` |
| `AWS_AUTH_FAILED` | 400 | `"AWS authentication failed: <reason>"` | Credentials sai, AssumeRole bị từ chối |
| `AWS_ACCESS_DENIED` | 403 | `"AWS access denied: <action>"` | Role thiếu quyền cho một lệnh đọc |
| `LLM_UNAVAILABLE` | 503 | `"LLM provider is unavailable"` | Provider lỗi / chưa cấu hình / không có MCP client trả lời kịp (`LLM_PROVIDER=mcp`) |
| `MAX_ITERATIONS` | — | `"Stopped after 10 reasoning steps without a conclusion"` | **Chỉ là event `error` của job**: agent hết số vòng và lượt chốt cuối (mục 3) cũng không ra kết luận |
| `AGENT_LIMIT` | — | `"Stopped at the time limit (240 s) without a conclusion"` | **Chỉ là event `error` của job**: chạm giới hạn thời gian / token / số lần gọi công cụ và lượt chốt cuối không ra kết luận |
| `JOB_NOT_FOUND` | 404 | `"Job not found"` | |
| `JOB_IN_PROGRESS` | 409 | `"A diagnosis is already running in this conversation"` | Gửi câu hỏi khi job trước của hội thoại chưa xong |
| `PROPOSAL_NOT_FOUND` | 404 | `"Proposal not found"` | |
| `PROPOSAL_NOT_PENDING` | 409 | `"Proposal is not waiting for a decision (status SUCCEEDED)"` | Quyết định cho đề xuất đã duyệt / từ chối / hết hạn (mục 7) |
| `REMEDIATION_DISABLED` | 400 | `"Remediation is not enabled for this connection"` | Duyệt đề xuất trên connection không có quyền sửa (mục 7) |
| `NOT_FOUND` | 404 | `"Not Found"` | Route không tồn tại |
| `METHOD_NOT_ALLOWED` | 405 | `"Method Not Allowed"` | Sai HTTP method |
| `NOT_IMPLEMENTED` | 501 | `"Checklist runs are not available yet"` | Tính năng chưa có (checklist) |
| `INTERNAL` | 500 | `"Internal server error"` | Lỗi không lường trước |

Không còn endpoint SSE: lỗi xảy ra **trong lúc** agent chạy nằm trong `events` của job (mục 8), event `error`.

## 0.1 Xác thực và phân vùng dữ liệu theo người dùng

- `AUTH_MODE=none` (mặc định, dev / test): không cần header; mọi request là người dùng cố định `local`.
- `AUTH_MODE=cognito` (bản triển khai): mọi endpoint **trừ** `GET /api/health` và `GET /api/auth/config` cần
  `Authorization: Bearer <access_token>` — **access token** của Cognito User Pool (không phải ID token), lấy bằng
  OAuth2 Authorization Code + PKCE qua Hosted UI. Thiếu / sai chữ ký / sai issuer / sai client / hết hạn → `401 UNAUTHORIZED`.
  Trên AWS, JWT authorizer của API Gateway kiểm token trước; backend đọc claims đã kiểm (hoặc tự kiểm bằng JWKS khi chạy ngoài Lambda).
- Người dùng = claim `sub`. Connection, conversation, job và proposal **thuộc về** người tạo ra nó (job / proposal thuộc người sở hữu hội thoại).
  Mọi danh sách chỉ trả tài nguyên của người gọi; đọc / sửa / xoá tài nguyên của người khác → **404** với mã `*_NOT_FOUND`
  như khi không tồn tại (không lộ là có tồn tại).

### `GET /api/auth/config` (không cần token)
```json
200 { "status_code": 200, "message": "OK",
      "data": { "mode": "cognito",                                              // "none" | "cognito"
                "domain": "https://autodiag-dev-1111.auth.ap-southeast-1.amazoncognito.com",  // Hosted UI; null khi none
                "client_id": "4abc...",                                         // public client (không có secret); null khi none
                "scopes": ["openid", "email", "profile"] } }
```
FE dùng để dựng URL `/oauth2/authorize`, đổi code ở `/oauth2/token`, refresh token, `/logout`. `redirect_uri` = `<origin>/auth/callback`,
`logout_uri` = `<origin>/` (phải nằm trong danh sách URL của app client).

### `GET /api/me`
```json
200 { "status_code": 200, "message": "OK",
      "data": { "user_id": "local" | "<cognito sub>", "username": "local" | "<cognito username>", "auth_mode": "none" | "cognito" } }
```

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
  "remediation_role_arn": "arn:aws:iam::123456789012:role/AutoAWSRemediation" | null,
  "remediation_enabled": true,      // server: có thể thực thi đề xuất đã duyệt (role trên, hoặc access key + REMEDIATION_ALLOW_ACCESS_KEYS)
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
  "external_id": "autoaws-7f3a...",
  "remediation_role_arn": "arn:aws:iam::123456789012:role/AutoAWSRemediation" }   // tuỳ chọn
```
`external_id` với `type=role`: theo luồng đã có trên nhánh `dev`, client sinh giá trị ngẫu nhiên trước khi tạo role, hiển thị trong form và dùng cùng giá trị cho trust policy / template / POST tạo connection. Server **giữ nguyên** giá trị client gửi để `AssumeRole` khớp trust policy; nếu bỏ qua hoặc `null`, server sinh `autoaws-` + 24 ký tự hex để tương thích client cũ. Giá trị tường minh phải dài 2–1224 ký tự, chỉ gồm chữ/số và `_+=,.@:/-` (định dạng STS). Thử lại verify trên cùng connection, không tạo connection mới.
```json
201 { "status_code": 201, "message": "Connection created", "data": Connection }   // status "pending"
```

### `GET /api/connections`
```json
200 { "status_code": 200, "message": "OK", "data": [Connection] }
```
### `GET /api/connections/setup`
Thông tin chuẩn bị tạo role, yêu cầu đăng nhập như các route connection khác. Khai báo trước route `/{id}`.
```json
200 { "status_code": 200, "message": "OK", "data": {
  "account_id": "111122223333" | null,
  "role_name": "AutoAWSReadOnly",
  "trust_principals": ["arn:aws:iam::111122223333:role/autoaws-agent-worker", "arn:aws:iam::111122223333:role/autoaws-action-executor"]
} }
```
`account_id=null` nếu nền tảng chưa cấu hình account hợp lệ. `trust_principals` dùng các role nền tảng đã cấu hình (giống template CloudFormation); khi không cấu hình role cụ thể, dùng ARN root của account nền tảng. UI không dựng policy khi thiếu account hợp lệ.

### `POST /api/connections/cloudformation-preview`
Tạo template **trước khi lưu connection**, yêu cầu đăng nhập. Body `{ "external_id": "autoaws-..." }` theo định dạng trên. Trả cùng schema `CloudFormationOut` như `GET /api/connections/{id}/cloudformation`, với chính External ID đã gửi, giữ trust policy theo các role nền tảng hiện tại. Thiếu account nền tảng hợp lệ → `503 CONNECTION_SETUP_UNAVAILABLE`, message `Connection setup is temporarily unavailable`.

### `GET /api/connections/{id}`
```json
200 { "status_code": 200, "message": "OK", "data": Connection }
```
### `PATCH /api/connections/{id}`
Bật / tắt quyền sửa sau khi đã tạo stack với `EnableRemediation=true`: `{ "remediation_role_arn": "arn:...:role/AutoAWSRemediation" | null }` (chỉ `type=role`).
```json
200 { "status_code": 200, "message": "Connection updated", "data": Connection }
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
Template có tham số `EnableRemediation` (mặc định `false`); `true` tạo thêm role `AutoAWSRemediation` chỉ có đúng các API ghi của danh mục hành động (mục 7, giới hạn Region; Route 53 chỉ `UPSERT` bản ghi `A`), output `RemediationRoleArn`.

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
  "status": "ok" | "error", "error": null, "duration_ms": 412,
  "cached": false                   // true: kết quả lấy từ cache của hội thoại, không gọi AWS lại
}

DiagnosisAnswer {
  "summary": "Subnet không có đường ra Internet; Security Group không phải nguyên nhân.",
  "root_causes": [                  // mỗi vấn đề độc lập một mục, chặn nhiều nhất đứng đầu; [] = không tìm ra lỗi
    {
      "statement": "Route table rtb-07c9 gắn với subnet subnet-0a1b không có tuyến 0.0.0.0/0 tới Internet Gateway.",
      "confidence": "high" | "medium" | "low",
      "evidence": [Evidence]
    }
  ],
  "fix_steps": [
    "Gắn lại subnet-0a1b vào route table public rtb-01aa, hoặc",
    "Thêm tuyến 0.0.0.0/0 → igw-0f3c vào rtb-07c9"
  ],
  "unverified": [
    { "text": "sshd có đang chạy trong máy không", "how_to_check": "sudo systemctl status sshd" }
  ],
  "confidence": "high" | "medium" | "low",   // độ tin cậy chung của cả câu trả lời
  "proposals": [ProposalRef],       // đề xuất sửa trong danh mục (mục 7); [] nếu không có
  "limit_reached": null | "max_iterations" | "time" | "tokens" | "tool_calls"   // khác null: agent phải chốt sớm, phần chưa kiểm tra nằm trong unverified
}

Evidence {
  "text": "rtb-07c9 chỉ có tuyến local 10.0.0.0/16",   // tiếng Việt, đọc được cho người dùng
  "source": "describe_route_tables",                 // tên công cụ đã trả dữ liệu này
  "resource_id": "rtb-07c9",                         // tuỳ chọn: ID tài nguyên được trích
  "field": "routes",                                 // tuỳ chọn: trường được trích
  "value": "10.0.0.0/16 → local",                    // tuỳ chọn: giá trị đọc được
  "verified": true,                                  // = (verification == "read")
  "verification": "read" | "inferred" | "not_found"  // do SERVER gán, xem dưới
}
```
Mọi chuỗi văn xuôi trong `DiagnosisAnswer` là **tiếng Việt** (system prompt ép model trả lời tiếng Việt); tên tài nguyên, lệnh, mã lỗi AWS giữ nguyên gốc.

ProposalRef {
  "action": "associate_route_table", "params": { "subnet_id": "subnet-0a1b", "route_table_id": "rtb-01aa" },
  "reason": "Gắn subnet về route table public",   // tiếng Việt, do model viết
  "proposal_id": "prop_..." | null,               // SERVER gán: đã tạo đề xuất chờ duyệt
  "error": null | "..."                           // SERVER gán khi không tạo được (tham số sai, kiểm tra trước không đạt, connection không bật sửa)
}

**Server kiểm tra bằng chứng** trước khi gửi `answer` (ràng buộc cứng #6), không tin cờ do model tự khai:
- `read`: `source` là công cụ đã chạy **thành công** trong hội thoại này, và nếu có `resource_id` thì ID đó xuất hiện trong kết quả của chính công cụ ấy.
- `inferred`: model tự đánh dấu là suy luận (`verified: false`), hoặc `source` không phải công cụ AWS (ví dụ `"user"` = người dùng nói).
- `not_found`: model khai là đọc được nhưng server không thấy lần gọi công cụ đó, hoặc không thấy `resource_id` trong kết quả → UI cảnh báo.

**Tương thích ngược:** câu trả lời lưu theo schema cũ (`cause` + `evidence` ở cấp trên) được server tự đổi sang một mục `root_causes` khi đọc ra; client chỉ cần hiểu schema mới.

**Model kết thúc bằng công cụ `submit_diagnosis`** (input = `DiagnosisAnswer` không có `verification`/`limit_reached`). Đây là kênh trả lời, không phải công cụ AWS: không có trong `GET /api/tools`, không phát `tool_call`/`tool_result`. Provider không gọi được công cụ thì vẫn trả lời bằng JSON thuần cùng schema.

**Giới hạn mỗi lượt** (cấu hình trong `.env`): `MAX_AGENT_ITERATIONS` (10 vòng), `MAX_AGENT_SECONDS` (240 giây; không áp cho `LLM_PROVIDER=mcp`), `MAX_TURN_TOKENS` (token vào + ra; chỉ khi provider báo usage), `MAX_TOOL_CALLS` (40). Chạm giới hạn → agent gọi model thêm **một lần chốt** (chỉ được `submit_diagnosis`) để trả phần đã xác nhận, kèm `limit_reached`; lần chốt cũng không ra kết luận → event `error` `MAX_ITERATIONS` / `AGENT_LIMIT`.

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

### `POST /api/conversations/{id}/messages` — tạo công việc chẩn đoán (job)
Request:
```json
{ "content": "Tôi không SSH được vào instance web-server, Security Group đã mở port 22 rồi." }
```
Server lưu câu hỏi, tạo một `Job` rồi giao cho agent-worker chạy **bất đồng bộ** (Lambda gọi kiểu Event; chạy local thì chạy nền trong tiến trình). Trả ngay:
```json
202 { "status_code": 202, "message": "Diagnosis started", "data": Job }   // status "queued"
```
Lỗi trước khi tạo job (hội thoại không tồn tại, connection chưa verify, đang có job khác chạy trong hội thoại này → `409 JOB_IN_PROGRESS`, body sai) → JSON lỗi theo mục 0.
Client hỏi lại `GET /api/jobs/{id}` (mục 8) mỗi 1–2 giây, đọc thêm `events` mới (theo `seq`) để vẽ timeline, tới khi `status` ∉ `queued | running`. Sau đó `GET /api/conversations/{id}` trả về đúng message của lượt này (server lưu trước khi job kết thúc).

Các `events` của job (thứ tự điển hình: `status` → (`tool_call` → `tool_result`)* → `answer` → `done`; lỗi: `error` rồi `done`):

| type | data | Ý nghĩa |
|---|---|---|
| `status` | `{ "text": "Planning checks…" }` | Trạng thái để hiển thị dòng "…ing" (`"Reading security groups…"`, `"Analyzing results…"`) |
| `tool_call` | `{ "id": "tc_1", "tool": "describe_instances", "input": {...} }` | Agent gọi công cụ |
| `tool_result` | `{ "id": "tc_1", "status": "ok", "output_summary": "...", "duration_ms": 300, "cached": false }` | Kết quả rút gọn; `cached: true` = lấy từ cache của hội thoại (mục 4) |
| `answer` | `{ "message_id": "msg_...", "content": "...", "answer": DiagnosisAnswer }` | Câu trả lời cuối |
| `error` | `{ "error": "LLM_UNAVAILABLE", "message": "LLM provider is unavailable" }` | Lỗi trong lúc chạy (cùng tên trường với JSON lỗi) |
| `done` | `{}` | Kết thúc |

**Lượt không có kết luận vẫn được lưu.** Khi lượt kết thúc không có `answer` (event `error`, hết vòng, worker lỗi, hoặc người dùng bấm Stop → `POST /api/jobs/{id}/cancel`), server lưu một message assistant với `answer: null`, `content` là câu giải thích tiếng Việt (ví dụ `"Chưa hoàn thành chẩn đoán: LLM provider is unavailable"`, `"Lượt chẩn đoán đã bị dừng trước khi có kết luận."`) và `tool_calls` gồm các công cụ đã chạy. Nhờ vậy lịch sử luôn xen kẽ user/assistant.

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

Phía LLM (không đổi API này):
- Tham số được kiểm tra theo `input_schema` trước khi gọi AWS; sai → kết quả `{"error": "INVALID_INPUT: ..."}` để model sửa và gọi lại.
- Thiếu quyền IAM → `{"error": "AccessDenied", "action": "ec2:DescribeNetworkAcls", "message": "..."}`.
- **Cache theo hội thoại:** cùng công cụ + cùng tham số trong vòng `TOOL_CACHE_TTL_SECONDS` (mặc định 300 giây, `0` = tắt) trả lại kết quả cũ kèm `"_cached": {"read_at", "age_seconds"}`. Mỗi công cụ đưa cho model có thêm tham số `refresh: true` để đọc lại dữ liệu sống (dùng khi người dùng báo vừa sửa).

---

## 5. Checklists — **ngoài phạm vi init**
Dự kiến: `POST /api/checklists/runs`, `GET /api/checklists/runs/{id}` (kết quả từng mục stream hoặc poll). Router để trống.

---

## 6. MCP bridge — MCP client đóng vai LLM (chỉ dev/test)

Chỉ bật khi `LLM_PROVIDER=mcp`. Dùng khi chưa có quyền gọi Bedrock/Anthropic: mỗi lượt `provider.chat()` của agent được xếp hàng, một MCP client (ví dụ Claude Code) lấy về, suy luận và trả lời. Vòng lặp agent, công cụ, sanitizer, job giữ nguyên. **Không phải endpoint cho FE**, không theo envelope (giao thức MCP).

- Endpoint: `http://localhost:8000/mcp/` (MCP Streamable HTTP; có dấu `/` cuối). Kết nối Claude Code: `claude mcp add --transport http autoaws-llm http://localhost:8000/mcp/`.
- Không có auth → chỉ chạy trên máy dev (bind `127.0.0.1`).
- Request chờ quá `MCP_BRIDGE_TIMEOUT_SECONDS` (mặc định 900) → agent nhận lỗi `LLM_UNAVAILABLE`.

| MCP tool | Tham số | Trả về |
|---|---|---|
| `next_llm_request` | `wait_seconds` (0–60, mặc định 30), `include_system` (mặc định `true`), `include_tools` (mặc định `true`) | Lượt cũ nhất đang chờ: `{ "pending": true, "request_id", "created_at", "system", "messages": [LLMMessage], "tools": [{name, description, input_schema}] }`; hết thời gian chờ mà không có lượt nào → `{ "pending": false }` |
| `respond_llm_request` | `request_id`, **một trong hai**: `tool_calls: [{ "name", "input" }]` (đọc thêm dữ liệu, hoặc `submit_diagnosis` để trả lời cuối — cách nên dùng) hoặc `text` (câu trả lời cuối = JSON `DiagnosisAnswer`, mục 3) | `{ "ok": true }`; tên tool không có trong `tools`, request không tồn tại / đã trả lời → lỗi MCP (`isError`) |
| `list_llm_requests` | — | `{ "requests": [{ "request_id", "created_at", "last_user_message" }] }` các lượt đang chờ |

`LLMMessage` = `{ "role": "user" | "assistant" | "tool", "content", "tool_calls"?: [{id, name, input}], "tool_call_id"?, "tool_name"? }` (`content` của `tool` là JSON kết quả công cụ đã sanitize).

---

## 7. Khắc phục có phê duyệt (human-in-the-loop)

Agent **không có công cụ ghi**: nó chỉ đưa `proposals` vào câu trả lời. Server kiểm tra từng đề xuất (schema, kiểm tra trước, snapshot tài nguyên) bằng session **chỉ đọc** rồi lưu thành `Proposal` chờ duyệt. Chỉ khi người dùng bấm Duyệt, executor mới gọi đúng API ghi của hành động đó bằng session ghi riêng, rồi kiểm chứng lại bằng session chỉ đọc.

### Schema `Proposal`
```json
{
  "id": "prop_...", "conversation_id": "conv_...", "message_id": "msg_...", "connection_id": "conn_...",
  "kind": "fix" | "rollback",
  "parent_id": null | "prop_...",            // rollback: đề xuất gốc; fix đề xuất lại sau góp ý: đề xuất bị thay
  "action": "associate_route_table", "params": { ... }, "reason": "...",
  "status": "PENDING_APPROVAL" | "APPROVED" | "EXECUTING" | "SUCCEEDED"
          | "REJECTED" | "EXPIRED" | "SUPERSEDED" | "STALE" | "FAILED" | "VERIFY_FAILED" | "ROLLED_BACK",
  "preview": {
    "summary": "Gắn subnet subnet-0a1b vào route table rtb-01aa",
    "changes": [ { "field": "Route table của subnet-0a1b", "before": "rtb-07c9 (không có 0.0.0.0/0)", "after": "rtb-01aa (0.0.0.0/0 → igw-0f3c)" } ],
    "impact": "...", "risk": "low" | "medium" | "high", "rollback": "...", "verify": "..."
  },
  "result": { ... } | null,                  // thực thi: id tạo ra (allocation, association…)
  "verification": { "ok": true, "details": "..." } | null,
  "error": null | "...",
  "history": [ { "status": "PENDING_APPROVAL", "at": "...", "note": "...", "by": null | "<user_id>" } ],   // nhật ký kiểm toán; `by` = người quyết định (duyệt / từ chối / góp ý)
  "created_at": "...", "updated_at": "...", "expires_at": "..."                // hết hạn sau 24 giờ
}
```
Văn bản trong `preview` là tiếng Anh do server sinh (nhãn) + ID tài nguyên; `reason` tiếng Việt do model viết.

### Vòng đời
`PENDING_APPROVAL` → (Duyệt) `APPROVED` → `EXECUTING` → `SUCCEEDED`.
- Từ chối → `REJECTED`; không quyết định trong 24 giờ → `EXPIRED`; góp ý → `SUPERSEDED` (agent đề xuất lại trong lượt hỏi tiếp).
- Lúc duyệt, server đọc lại tài nguyên: khác snapshot lúc xem trước → `STALE`, không ghi gì.
- Trước khi ghi, các hành động EC2 chạy thử với `DryRun=True` (chỉ trên AWS thật, `REMEDIATION_DRY_RUN=true`): AWS trả `DryRunOperation` thì mới ghi thật (lịch sử có ghi chú `dry run passed`); bị từ chối quyền → `FAILED` (`error` bắt đầu bằng `Permission:`); endpoint không trả `DryRunOperation` (trình giả lập) → `FAILED`, không ghi tiếp. Route 53 và ELB không có DryRun.
- Lỗi khi gọi API ghi → `FAILED` (kèm `error`).
- `RUNTIME=local`, backend khởi động lại giữa chừng: `APPROVED` (chưa ghi) được chạy tiếp; `EXECUTING` đã có `result` được kiểm chứng; `EXECUTING` chưa có `result` → `FAILED` với `error` `"Interrupted: …"` (không ghi lại lần hai — người dùng kiểm tra tài nguyên rồi hỏi lại).
- Kiểm chứng sau khi sửa không đạt → `VERIFY_FAILED` + tạo đề xuất `kind: "rollback"` (cũng phải duyệt). Hoàn tác xong → đề xuất gốc `ROLLED_BACK`.
- Thực thi chạy nền: response của quyết định trả `APPROVED`; client hỏi lại `GET /api/proposals/{id}` tới khi hết `APPROVED` / `EXECUTING`.
- Trên AWS (`RUNTIME=lambda`, mục 9): mỗi đề xuất là một lượt chạy state machine `remediation-flow` (Step Functions): gửi email SNS → chờ duyệt `.waitForTaskToken` (24 giờ, hết hạn → `EXPIRED`) → agent-worker kiểm tra lại (role chỉ đọc) → action-executor thực thi (role `AutoAWSRemediation`) → agent-worker kiểm chứng → email kết quả. Quyết định của người dùng được chuyển vào state machine bằng `SendTaskSuccess` / `SendTaskFailure`. Chạy local (`RUNTIME=local`) thì các bước này chạy nền trong backend, cùng trạng thái và API.

### `GET /api/proposals`
Query tuỳ chọn `?conversation_id=…`, `?status=PENDING_APPROVAL`. Mới nhất trước.
```json
200 { "status_code": 200, "message": "OK", "data": [Proposal] }
```
### `GET /api/proposals/{id}`
```json
200 { "status_code": 200, "message": "OK", "data": Proposal }
```
### `POST /api/proposals/{id}/decision`
```json
{ "decision": "approve" | "reject" | "feedback", "feedback": "chỉ mở 8080 cho IP công ty" }   // feedback bắt buộc khi decision = feedback
200 { "status_code": 200, "message": "Proposal approved", "data": { "proposal": Proposal, "followup_question": null | "..." } }
```
`followup_question` (chỉ khi góp ý): câu hỏi tiếng Việt client gửi tiếp vào hội thoại để agent đề xuất lại.
Lỗi: `PROPOSAL_NOT_PENDING` (409), `REMEDIATION_DISABLED` (400, khi duyệt).

### `GET /api/remediation/actions`
Danh mục hành động: `[{ "name", "label", "description", "input_schema", "aws_actions" }]` — `aws_actions` là API **ghi** mà role `AutoAWSRemediation` cấp.

| name | Sửa | API ghi | Kiểm tra trước | Kiểm chứng | Hoàn tác |
|---|---|---|---|---|---|
| `associate_route_table` | KB1 | ec2:AssociateRouteTable / ReplaceRouteTableAssociation | Route table đích cùng VPC, có 0.0.0.0/0 → igw đang active | Route table hiệu lực của subnet có tuyến tới IGW | Gắn lại route table cũ (hoặc về main) |
| `create_route_to_igw` | KB1 | ec2:CreateRoute | Chưa có 0.0.0.0/0; IGW đã gắn vào VPC | Tuyến active | ec2:DeleteRoute đúng tuyến vừa tạo |
| `authorize_sg_ingress` | KB2 | ec2:AuthorizeSecurityGroupIngress | Quy tắc chưa có; **từ chối 22 / 3389 từ 0.0.0.0/0 hoặc ::/0** | Quy tắc có trong SG | ec2:RevokeSecurityGroupIngress |
| `allocate_and_associate_eip` | KB2 | ec2:AllocateAddress, AssociateAddress | Instance đang chạy, chưa có Elastic IP | Public IP của instance = Elastic IP | DisassociateAddress + ReleaseAddress |
| `upsert_a_record` | KB2 | route53:ChangeResourceRecordSets (UPSERT A) | Bản ghi A **đã có** trong hosted zone của tài khoản; IP mới là IP của tài khoản (hoặc `instance_id` → IP hiện tại lúc thực thi) | Route 53 trả giá trị mới, thay đổi INSYNC | UPSERT lại giá trị cũ |
| `modify_health_check_path` | KB3 | elasticloadbalancing:ModifyTargetGroup | Đường dẫn bắt đầu bằng `/` | Mọi target healthy (chờ tối đa ~5 chu kỳ) | Đặt lại đường dẫn cũ |

---

## 8. Jobs — công việc chạy nền

### Schema `Job`
```json
{
  "id": "job_...", "type": "diagnosis", "conversation_id": "conv_...",
  "status": "queued" | "running" | "succeeded" | "failed" | "cancelled",
  "cancel_requested": false,
  "message_id": "msg_..." | null,        // message assistant đã lưu (khi xong)
  "error": null | { "error": "LLM_UNAVAILABLE", "message": "..." },
  "events": [ { "seq": 0, "type": "status", "data": { "text": "Reasoning…" } } ],   // mục 3
  "created_at": "...", "updated_at": "..."
}
```
`succeeded` = có `answer`; `failed` = kết thúc bằng event `error`; `cancelled` = dừng theo yêu cầu. Job tự xoá sau `JOB_TTL_DAYS` (mặc định 7, DynamoDB TTL); hội thoại và message vẫn còn.

### `GET /api/jobs/{id}`
Query tuỳ chọn `?after=<seq>`: chỉ trả các event có `seq` > giá trị này (client đã có phần trước).
```json
200 { "status_code": 200, "message": "OK", "data": Job }
```
Job `queued` / `running` mà quá `JOB_STALE_SECONDS` (mặc định 900) không cập nhật → server đánh dấu `failed` (`WORKER_LOST`) và lưu ghi chú như lượt không có kết luận.

### `POST /api/jobs/{id}/cancel`
Yêu cầu dừng: agent-worker kiểm tra cờ giữa các bước và kết thúc lượt (`cancelled`, ghi chú `"Lượt chẩn đoán đã bị dừng trước khi có kết luận."`). Job đã kết thúc → trả nguyên trạng.
```json
200 { "status_code": 200, "message": "Cancel requested", "data": Job }
```

---

## 9. Triển khai (thông tin cho FE/BE, không đổi API)

- `RUNTIME=local` (mặc định): một tiến trình FastAPI; job và luồng duyệt chạy nền trong tiến trình.
- `RUNTIME=lambda`: API Gateway HTTP API → Lambda `api-handler` (cùng app FastAPI, adapter Mangum) · Lambda `agent-worker` (chẩn đoán, kiểm tra kết nối, kiểm tra lại / kiểm chứng đề xuất) · Lambda `action-executor` (thực thi đề xuất đã duyệt, lưu task token) · Step Functions `remediation-flow` · SNS. Hạ tầng: `infra/cdk/`.
- `POST /api/connections/{id}/verify` chạy trong agent-worker (gọi đồng bộ): api-handler không có quyền vào tài khoản người dùng.
- Đăng nhập: stack `Auth` (Cognito User Pool, Hosted UI, app client public + PKCE). HTTP API gắn JWT authorizer cho mọi route trừ
  `GET /api/health` và `GET /api/auth/config`. Callback / logout URL của app client = URL CloudFront (hoặc `frontendUrl` khi gắn tên miền riêng) + `http://localhost:5173` (chỉ `envName=dev`); một lần `cdk deploy` là đủ.

---

## Danh sách công cụ (tên ổn định; `label` do backend trả về, FE không tự đặt)

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
| `describe_nat_gateways` | network | NAT gateways | ec2:DescribeNatGateways |
| `describe_addresses` | network | Elastic IPs | ec2:DescribeAddresses |
| `route53_list_records` | dns | Route 53 records | route53:ListHostedZones, ListResourceRecordSets |
| `resolve_dns_public` | dns | Public DNS lookup | route53:ListHostedZones (kiểm tra tên được phép) + truy vấn DNS công khai (`DNS_RESOLVERS`, mặc định 8.8.8.8, 1.1.1.1). Chỉ phân giải tên người dùng đã nhắc trong hội thoại (và tên cha/con của nó), tên thuộc hosted zone của tài khoản, hoặc tên DNS đọc được từ Route 53 / load balancer — chặn rò dữ liệu qua DNS khi log chứa chỉ thị độc hại |
| `elbv2_describe_load_balancers` | elb | Load balancers | elasticloadbalancing:DescribeLoadBalancers, DescribeListeners |
| `elbv2_describe_target_health` | elb | Target health | elasticloadbalancing:DescribeTargetGroups, DescribeTargetHealth |
| `cloudwatch_get_metric_data` | metrics | CloudWatch metrics | cloudwatch:GetMetricData, ListMetrics |
| `cloudwatch_describe_alarms` | metrics | CloudWatch alarms | cloudwatch:DescribeAlarms |
| `logs_describe_log_groups` | logs | Log groups | logs:DescribeLogGroups |
| `logs_insights_query` | logs | CloudWatch Logs query | logs:StartQuery, GetQueryResults |
| `cloudtrail_lookup_events` | cloudtrail | CloudTrail events | cloudtrail:LookupEvents |
