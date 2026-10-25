# AutoAWS — Kế hoạch Backend (bản init)

> Trạng thái: **đã duyệt (2026-10-16)**. Thực hiện theo thứ tự mục 5; tick checkbox khi xong.
> Đọc trước: `docs/SYSTEM_OVERVIEW.md` (hệ thống làm gì), `docs/API_CONTRACT.md` (endpoint & schema — nguồn sự thật, không định nghĩa lại ở đây).

## 1. Mục tiêu bản init

Một server chạy **local** cho phép:
1. Tạo **kết nối tài khoản AWS** (Access Key hoặc Role ARN + ExternalId) và **verify** → "Connected" (mốc **M1**).

> **Ngôn ngữ:** `message` trong envelope, status SSE, label/mô tả tool → **tiếng Anh**. **Câu trả lời của agent** (`DiagnosisAnswer`, `content` assistant) → **tiếng Việt** (system prompt ép). Comment code tiếng Anh; tài liệu tiếng Việt.
2. Chat chẩn đoán: nhận câu hỏi → **vòng lặp agent** gọi **công cụ đọc AWS** thật → trả lời có cấu trúc, **stream** từng bước ra UI.
3. Chạy được **end-to-end không cần LLM key** nhờ `MockProvider`; ưu tiên LLM thật qua API OpenAI-compatible (Ollama tự host), có thể chọn Bedrock.

Ngoài phạm vi init (chừa chỗ, không làm): checklist runner, auth người dùng, metrics/logs/CloudTrail đầy đủ (M3), đóng gói Lambda, DynamoDB.

## 2. Stack & lý do

| Thành phần | Chọn | Lý do |
|---|---|---|
| Ngôn ngữ | Python ≥ 3.12 (máy dev: 3.14) | Khớp tài liệu (Lambda Python); boto3 là SDK AWS đầy đủ nhất |
| Web framework | **FastAPI** + uvicorn | Dễ nhất để có REST + SSE + validation (pydantic) + docs tự động `/docs` |
| AWS SDK | boto3 | Chuẩn |
| Streaming | `sse-starlette` | SSE trên FastAPI, vài dòng |
| Lưu trữ | SQLite qua **SQLModel** | Không cần cài DB; model = pydantic = schema API; sau đổi DynamoDB chỉ thay lớp `storage/` |
| Cấu hình | pydantic-settings + `.env` | |
| Test | pytest + **moto** (giả lập AWS) + httpx | Test tool AWS không cần tài khoản thật |
| Lint/format | ruff | Một tool cho cả lint + format |
| Quản lý gói | `pyproject.toml` + `python -m venv` + pip | Máy dev không có uv; nếu ai có uv thì `uv sync` vẫn chạy được từ pyproject |

## 3. Cấu trúc thư mục `backend/`

```
backend/
├── pyproject.toml            # deps, ruff config, pytest config
├── .env.example              # mọi biến môi trường, giá trị rỗng/mặc định an toàn
├── README.md                 # cách chạy 5 dòng
├── Dockerfile
├── app/
│   ├── main.py               # create_app(): CORS, mount routers, startup tạo DB
│   ├── config.py             # Settings: LLM_PROVIDER, DB_PATH, PLATFORM_AWS_*, MAX_AGENT_ITERATIONS, ...
│   ├── errors.py             # AppError(error, status, message) + exception handlers → JSON lỗi {status_code, message, error, path, timestamp}
│   ├── responses.py          # ok(data, message="OK", status_code=200) → envelope {status_code, message, data}; mọi router dùng hàm này
│   ├── api/
│   │   ├── health.py
│   │   ├── connections.py    # CRUD + verify + cloudformation
│   │   ├── conversations.py  # CRUD + POST messages (SSE)
│   │   ├── tools.py          # GET /api/tools từ registry
│   │   └── checklists.py     # router rỗng, TODO sau init
│   ├── aws/
│   │   ├── credentials.py    # resolve_session(connection) -> boto3.Session
│   │   │                     #   - access_key: Session trực tiếp
│   │   │                     #   - role: Session nền tảng → sts.assume_role(RoleArn, ExternalId) → Session tạm
│   │   │                     #   cache in-memory {connection_id: (session, expires_at)}
│   │   ├── cloudformation.py # render template YAML role chỉ đọc (trust tới PLATFORM account + ExternalId)
│   │   ├── registry.py       # ToolSpec(name, group, description, input_schema, aws_actions, fn); REGISTRY dict
│   │   └── tools/
│   │       ├── __init__.py   # import tất cả để đăng ký
│   │       ├── compute.py    # get_caller_identity, describe_instances, describe_instance_status, ssm_describe_instance_information
│   │       ├── network.py    # describe_security_groups, describe_network_acls, describe_route_tables, describe_subnets, describe_internet_gateways
│   │       ├── dns.py        # route53_list_records, resolve_dns_public (dnspython)
│   │       ├── elb.py        # elbv2_describe_load_balancers, elbv2_describe_target_health
│   │       ├── metrics.py    # cloudwatch_get_metric_data   — stub M3
│   │       ├── logs.py       # logs_insights_query          — stub M3
│   │       └── cloudtrail.py # cloudtrail_lookup_events     — stub M3
│   ├── agent/
│   │   ├── loop.py           # run_agent(conversation, question, session, provider) -> AsyncIterator[AgentEvent]
│   │   ├── prompts.py        # SYSTEM_PROMPT (đường đi kết nối), ANSWER_FORMAT (JSON DiagnosisAnswer)
│   │   └── schemas.py        # DiagnosisAnswer, Evidence, Unverified, AgentEvent (status/tool_call/tool_result/answer/error/done)
│   ├── llm/
│   │   ├── base.py           # LLMProvider (Protocol): chat(messages, tools) -> LLMResponse(text | tool_calls)
│   │   ├── mock.py           # MockProvider: chọn tool theo từ khoá, trả DiagnosisAnswer mẫu
│   │   ├── anthropic.py      # AnthropicProvider: raise NotImplementedError("TODO")  ← placeholder
│   │   ├── openai_compatible.py # OpenAICompatibleProvider: Chat Completions + function calling
│   │   ├── bedrock.py        # BedrockProvider: Converse qua adapter app/aws/bedrock.py
│   │   └── factory.py        # get_provider(settings.LLM_PROVIDER)
│   ├── sanitizer.py          # sanitize(obj) -> obj: che AKIA…, secret, email, token, ARN account id?; truncate(list, n)
│   └── storage/
│       ├── db.py             # engine, get_session(), init_db()
│       ├── models.py         # Connection, Conversation, Message, ToolCall (SQLModel, table=True)
│       └── repo.py           # hàm CRUD đơn giản (tránh ORM rải khắp router)
└── tests/
    ├── conftest.py           # app test client, SQLite tạm, moto mock_aws
    ├── test_health.py
    ├── test_connections.py   # tạo/verify access_key với moto STS/EC2
    ├── test_tools_network.py # describe_security_groups… trên moto
    ├── test_agent_loop.py    # MockProvider → stream đủ events, answer đúng schema
    └── test_sanitizer.py
```

## 4. Thiết kế các phần quan trọng

### 4.1 Credentials (`aws/credentials.py`)
```python
def resolve_session(conn: Connection) -> boto3.Session:
    if conn.type == "access_key":
        return boto3.Session(aws_access_key_id=..., aws_secret_access_key=..., region_name=conn.region)
    # role
    base = platform_session()  # credentials từ Settings đọc trực tiếp backend/.env
    resp = base.client("sts").assume_role(RoleArn=conn.role_arn, RoleSessionName=f"autoaws-{conn.id}",
                                          ExternalId=conn.external_id, DurationSeconds=900)
    return boto3.Session(**map_creds(resp["Credentials"]), region_name=conn.region)
```
- Cache session theo `connection_id`, hết hạn trước `Expiration` 60s thì xin lại.
- Credentials tạm **không** ghi DB, **không** log. Secret key của access_key lưu SQLite **chỉ cho dev** — ghi cảnh báo trong README; mục "sau init": mã hoá bằng KMS / lưu DynamoDB.

### 4.2 Tool registry (`aws/registry.py`)
```python
@dataclass
class ToolSpec:
    name: str; group: str; label: str; description: str   # label/description tiếng Anh (UI + LLM)
    input_schema: dict          # JSON Schema → đưa thẳng cho LLM tool-use
    aws_actions: list[str]      # để sinh IAM policy + hiển thị UI
    fn: Callable[[boto3.Session, dict], dict]

def tool(spec) -> decorator  # đăng ký vào REGISTRY
```
- Model **chỉ** gọi được tên có trong `REGISTRY`. Tên không có → `error` event, không crash.
- Mỗi tool: nhận `(session, input)`, trả **dict JSON-serializable, đã rút gọn** (chỉ trường cần cho chẩn đoán, ví dụ instance: id, name, state, public_ip, private_ip, subnet_id, vpc_id, sg_ids, status_checks). Phân trang bằng paginator; giới hạn `max_items`.
- `AccessDenied`/`ClientError` → trả `{"error": "AccessDenied: ..."}` để agent biết và ghi vào `unverified`.

### 4.3 LLM provider (`llm/base.py`)
```python
class LLMMessage(BaseModel): role: Literal["system","user","assistant","tool"]; content: str
class ToolCallRequest(BaseModel): id: str; name: str; input: dict
class LLMResponse(BaseModel): text: str | None; tool_calls: list[ToolCallRequest]; stop_reason: str

class LLMProvider(Protocol):
    name: str
    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse: ...
```
- `MockProvider` (demo không cần key): lượt 1 nhìn từ khoá trong câu hỏi → trả `tool_calls` (ví dụ chứa "ssh" → `describe_instances`, `describe_security_groups`, `describe_route_tables`; "502"/"5xx" → `elbv2_describe_load_balancers`, `elbv2_describe_target_health`; "dns"/"tên miền" → `resolve_dns_public`, `route53_list_records`, `describe_instances`); lượt 2 trả `text` là JSON `DiagnosisAnswer` **sinh từ kết quả tool thật** ở mức đơn giản (liệt kê bằng chứng, `confidence: "low"`, `cause` ghi "MockProvider — chưa cấu hình LLM, chỉ liệt kê bằng chứng chưa suy luận"). Mục đích: UI và pipeline chạy thật từ đầu đến cuối.
- `OpenAICompatibleProvider` (`LLM_PROVIDER=openai`) là hướng ưu tiên: HTTP async qua `httpx` tới `OPENAI_BASE_URL/chat/completions`, model do `OPENAI_MODEL` chọn; API key tùy server, local Ollama có thể để trống. Tool schema map sang `tools[].function.parameters`; arguments JSON map về `ToolCallRequest`; kết quả dùng role `tool` và `tool_call_id`. Giữ nội dung assistant và mọi call ID qua các lượt; hỗ trợ nhiều tool trong một response.
- Chỉ chấp nhận phản hồi hoàn chỉnh và arguments là JSON object. Phản hồi lỗi/rỗng/bị cắt, HTTP lỗi, timeout hoặc mạng lỗi → `LLMError` an toàn, không đưa payload/keys vào log hay SSE. Không tự fallback sang dịch vụ khác. Giới hạn output cấu hình bằng `OPENAI_MAX_TOKENS`, tên trường `max_tokens` hoặc `max_completion_tokens` tùy model/server; timeout qua `OPENAI_TIMEOUT_SECONDS`.
- `BedrockProvider` đã triển khai Converse qua adapter `app/aws/bedrock.py`, boto3 chạy ngoài event loop. `AnthropicProvider` vẫn là placeholder; không bắt buộc để dùng OpenAI-compatible.

### 4.4 Agent loop (`agent/loop.py`)
```
messages = [system(SYSTEM_PROMPT + ANSWER_FORMAT), *history, user(question)]
for i in range(MAX_AGENT_ITERATIONS):          # mặc định 10, phạm vi 1–10
    yield status("Reasoning…")                 # trước mỗi tool: status(f"Reading {spec.label.lower()}…")
    resp = await provider.chat(messages, tools)
    if resp.tool_calls:
        for tc in resp.tool_calls:
            yield tool_call(tc)
            raw = REGISTRY[tc.name].fn(session, tc.input)      # try/except → error dict
            clean = sanitizer.sanitize(raw)
            yield tool_result(tc.id, summarize(clean))
            messages.append(tool_result_message(tc.id, clean))
        continue
    answer = parse_diagnosis(resp.text)       # JSON → DiagnosisAnswer; parse lỗi → retry 1 lần với nhắc "trả JSON"
    save message + tool_calls; yield answer; break
else: yield error("MAX_ITERATIONS")
yield done
```
- Lịch sử hội thoại: nạp lại messages trước (gồm tool results đã rút gọn) để "hỏi tiếp không phải đọc lại".
- `SYSTEM_PROMPT` (tiếng Anh): vai trò, **thứ tự kiểm tra theo đường đi kết nối** (DNS → IP → route table → NACL → SG → LB → instance → app), quy tắc "mọi kết luận phải có bằng chứng", "không đoán — ghi vào unverified kèm lệnh tự kiểm tra", chỉ gọi tool trong danh sách, trả JSON đúng schema `DiagnosisAnswer`, **văn xuôi trong câu trả lời luôn là tiếng Việt** (giữ nguyên tên tài nguyên, lệnh, mã lỗi AWS). Prompt viết bằng tiếng Anh (model tuân thủ tốt hơn), chỉ có chỉ thị ngôn ngữ đầu ra là tiếng Việt.

### 4.5 Sanitizer (`sanitizer.py`)
- Regex che: `AKIA[0-9A-Z]{16}`, chuỗi 40 ký tự base64 cạnh từ "secret", email, `Bearer …`, `password=…`, private key block.
- Rút gọn: list > N phần tử → giữ N + `"_truncated": k`; chuỗi > M ký tự → cắt.
- Chạy **trước mọi lần** đưa dữ liệu vào provider và trước khi lưu `output_summary`.

### 4.6 CloudFormation template (`aws/cloudformation.py`)
Role `AutoAWSReadOnly`: trust policy `Principal: {AWS: <PLATFORM_AWS_ACCOUNT_ID>}` + `Condition: {StringEquals: {sts:ExternalId: <external_id>}}`; permission policy **Allow** danh sách action trong `REGISTRY[*].aws_actions` (sinh tự động → luôn khớp code) + **Deny** rõ ràng `s3:GetObject`, `secretsmanager:*`, `ssm:GetParameter*`, `kms:Decrypt`.

### 4.7 Envelope response (`responses.py`, `errors.py`)
- Mọi endpoint JSON trả qua `ok(data, message, status_code)` → `{"status_code", "message", "data"}`. Router **không** trả model trực tiếp.
- `AppError(error="CONNECTION_NOT_FOUND", status=404, message="Connection not found")`; exception handler (cả cho `RequestValidationError` → `VALIDATION_ERROR` 422 và `Exception` → `INTERNAL` 500) sinh `{"status_code", "message", "error", "path", "timestamp"}`. Không bao giờ lộ stack trace trong `message`.
- SSE endpoint là ngoại lệ duy nhất (xem contract mục 0).
- Test: `test_envelope.py` kiểm tra 1 case thành công, 1 case 404, 1 case 422 đúng hình dạng.

### 4.8 Cấu hình (`.env.example`)
```
APP_ENV=dev
DB_PATH=./autoaws.db
LLM_PROVIDER=mock              # mock | openai | bedrock | anthropic (stub)
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=                 # tên model trên server; ví dụ qwen3:8b đã pull trong Ollama
OPENAI_API_KEY=               # local Ollama có thể để trống
OPENAI_TIMEOUT_SECONDS=120
OPENAI_MAX_TOKENS=4096
OPENAI_TOKEN_LIMIT_FIELD=max_tokens
ANTHROPIC_API_KEY=
BEDROCK_MODEL_ID=
BEDROCK_REGION=
PLATFORM_AWS_ACCOUNT_ID=       # cần cho type=role (tài khoản nền tảng)
AWS_ACCESS_KEY_ID=            # đọc trực tiếp từ backend/.env
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=            # bắt buộc với credentials tạm thời
AWS_DEFAULT_REGION=ap-southeast-1
PLATFORM_AWS_PROFILE=          # fallback khi không cấu hình credentials
MAX_AGENT_ITERATIONS=10
CORS_ORIGINS=http://localhost:5173
```

## 5. Lộ trình thực hiện (tick khi xong)

- [x] **B1 Scaffold**: `pyproject.toml`, `app/main.py`, `config.py`, `errors.py`, `responses.py`, `api/health.py`, `.env.example`, README. Chạy `uvicorn app.main:app --reload` → `GET /api/health` trả đúng envelope; test envelope 200/404/422.
- [x] **B2 Storage + Connections (access_key)**: models, db, repo; `POST/GET/DELETE /api/connections`; `POST …/verify` dùng `resolve_session` nhánh access_key. Test moto.
- [x] **B3 Role ARN**: nhánh assume_role + cache; `GET …/cloudformation`. Test với moto STS.
- [x] **B4 Tool registry + nhóm compute/network/dns/elb**: 13 tool trong contract, mỗi tool có test moto. Stub 3 tool M3. `GET /api/tools`.
- [x] **B5 LLM interface + MockProvider + 2 placeholder**.
- [x] **B6 Agent loop + SSE**: `POST /api/conversations/{id}/messages` stream đủ event theo contract; lưu message trước `done`. Test với MockProvider.
- [x] **B7 Sanitizer** + gắn vào loop. Test.
- [x] **B8 Conversations CRUD** còn lại, tiêu đề tự đặt từ câu hỏi đầu.
- [x] **B9 Dockerfile** + `docker compose` ở root (backend + frontend).
- [x] **B10 Cập nhật `AGENTS.md`** mục "Trạng thái" + cách chạy thật.

Hoàn thành 2026-10-16: 25 test pass (`pytest`), ruff sạch. Ghi chú triển khai so với plan: `ToolSpec` có thêm `label` (UI) và `stub` (3 tool M3 vẫn đăng ký để policy/`/api/tools` đầy đủ, gọi sẽ trả `NOT_IMPLEMENTED`); `run_tool` bắt mọi exception để tool không bao giờ làm đứt stream; `list_tools()` sắp theo thứ tự nhóm (đường đi chẩn đoán).

Ước tính: B1–B3 ≈ 1 ngày, B4 ≈ 1.5 ngày, B5–B7 ≈ 1.5 ngày, B8–B10 ≈ 0.5 ngày.

## 6. Sau init (không làm bây giờ)
- `AnthropicProvider` thật, Guardrails cho Bedrock (Converse đã triển khai).
- Tool M3: `cloudwatch_get_metric_data`, `logs_insights_query` (giới hạn khung thời gian, lọc mức lỗi, tóm tắt), `cloudtrail_lookup_events`.
- Checklist runner (parser → chạy từng mục → lưu từng mục).
- Auth (Cognito JWT) — middleware FastAPI `Depends(current_user)`; mọi bảng thêm `user_id`.
- Lưu trữ DynamoDB + KMS; đóng gói `api-handler` / `agent-worker` lên Lambda (Mangum); Step Functions cho checklist.
- Giới hạn chi phí: cache kết quả tool theo (connection, tool, input) trong phiên; đếm token.

## 7. Quy tắc bắt buộc (cho mọi người/agent sửa backend)
1. Không thêm bất kỳ AWS action nào ngoài `Describe*/List*/Get*/LookupEvents/StartQuery/GetQueryResults/GetMetricData`. PR có action ghi → từ chối.
2. Không `print`/log credentials, secret, nội dung `.env`.
3. Dữ liệu đi vào provider **phải** qua `sanitizer.sanitize`.
4. Tool mới = thêm 1 hàm có decorator `@tool(...)` trong `aws/tools/` + test moto + dòng trong bảng `API_CONTRACT.md`. Không gọi boto3 ở nơi khác ngoài `aws/`.
5. Đổi endpoint/schema → sửa `API_CONTRACT.md` trước.

## Mốc Bedrock Converse local (2026-10-25)

- [x] BedrockProvider dùng Converse/tool use qua adapter trong `app/aws/`, chạy ngoài event loop.
- [x] Demo qua API/UI bằng `AGENT_DEMO_MODE`, tool giả registry và kết nối AWS đã xác thực.
- [x] Giới hạn cấu hình 1–10 lượt model, mặc định 10; lỗi hoặc hết lượt kết thúc SSE.
- [x] Kiểm thử wire format bằng Stubber và luồng SSE bằng moto; hướng dẫn chạy local.
- [ ] Smoke test Bedrock thật qua UI với model/region và credentials trên máy.

Bedrock đã triển khai; Anthropic và Guardrails vẫn thuộc phần sau init. Quyền invoke model
thuộc identity nền tảng, không thêm vào policy tool đọc AWS của tài khoản chẩn đoán.

## Credentials trực tiếp từ .env (2026-10-25)

- [x] Settings đọc AWS access key, secret, session token dạng SecretStr và default region từ backend/.env theo đường dẫn tuyệt đối.
- [x] AssumeRole/Bedrock dùng chung platform_session; ưu tiên credentials cấu hình trực tiếp, thiếu cặp key/secret báo lỗi; profile/default chain là fallback.
- [x] Docker Compose không cần mount ~/.aws; cập nhật cấu hình mẫu và hướng dẫn.
- [x] Kiểm thử dotenv khi không có shared credentials, token tạm thời, lỗi cấu hình và AssumeRole với moto.

- [x] API `GET /api/connections/setup` trả account ID công khai và tên role để UI điền sẵn trust policy; thiếu/sai account ID trả null, không gọi AWS hay trả credentials.

- [x] Preview CloudFormation qua POST trước khi tạo connection, không ghi DB/gọi AWS; kiểm tra External ID và account ID, thêm DescribeRegions cho Verify. Endpoint CloudFormation theo connection cũ vẫn tương thích.

- [x] Phân biệt Bedrock ValidationException với thông báo Operation not allowed: trả lỗi hữu ích và log Request ID, giữ kín payload dịch vụ; kiểm thử không lộ dữ liệu.
- [ ] Smoke test inference Bedrock thật bị chặn bởi Operation not allowed trên request tối giản; cần AWS xác minh hạn chế tài khoản (2026-10-26).

## Mốc OpenAI-compatible / Ollama (2026-10-26)

- [x] Thêm `OpenAICompatibleProvider` dùng Chat Completions/function calling qua HTTP async; factory chọn bằng `LLM_PROVIDER=openai`, Bedrock và mock vẫn dùng được.
- [x] Đọc endpoint/model/API key/timeout/giới hạn output trực tiếp từ `backend/.env`; API key là `SecretStr`, tùy chọn cho local Ollama. `httpx` là dependency runtime.
- [x] Map đầy đủ history, nhiều tool calls và `tool_call_id`; kiểm tra cấu trúc response, JSON arguments; xử lý HTTP/network/timeout an toàn.
- [x] Kiểm thử protocol và SSE: tool giả → kết quả đã sanitize → DiagnosisAnswer/lưu lịch sử; tool ngoài registry bị từ chối; lỗi kết thúc stream; tối đa 10 lượt.
- [x] Hướng dẫn dùng Ollama, endpoint tương thích khác, restart backend và Docker gọi model server trên host trong `backend/README.md`.
- [x] Kiểm tra backend: 91 test pass (40 test OpenAI-compatible mới), `ruff check app tests` và kiểm tra format các file Python đã sửa đều pass.
- [ ] Smoke test inference với Ollama thật: máy hiện chưa cài/chạy model server; không tải model tự động.
