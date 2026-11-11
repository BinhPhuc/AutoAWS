# AutoAWS backend

FastAPI + boto3. Thiết kế chi tiết: `../docs/BACKEND_PLAN.md`; hợp đồng API: `../docs/API_CONTRACT.md`.

## Chạy

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # DynamoDB: điền DYNAMODB_TABLE, DYNAMODB_REGION; hoặc local: STORAGE_BACKEND=sqlite
uvicorn app.main:app --reload # http://localhost:8000/docs
```

### Windows / PowerShell

Dùng Python của `.venv` trực tiếp để tránh cài nhầm vào Python hệ thống:

```powershell
cd backend
py -m venv .venv              # Chỉ cần khi chưa có .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Nếu Python 3.15 báo `Failed building wheel for PyYAML` và yêu cầu Microsoft Visual C++,
pip đang biên dịch extension C vì không tìm được wheel phù hợp. Có thể dùng bản Python
thuần bằng biến build [PyYAML hỗ trợ](https://github.com/yaml/pyyaml/blob/6.0.3/setup.py):

```powershell
$env:PYYAML_FORCE_LIBYAML = '0'
try {
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
} finally {
    Remove-Item Env:PYYAML_FORCE_LIBYAML
}
.\.venv\Scripts\python.exe -c "import yaml; print(yaml.__version__, yaml.__with_libyaml__)"
```

`__with_libyaml__ = False` nghĩa là đang dùng bản Python thuần; vẫn đọc/ghi YAML bình thường.
Các cảnh báo `License classifiers` / `bdist_wheel` không phải nguyên nhân gây lỗi này.

## Chọn LLM (`LLM_PROVIDER`)

Backend đọc cấu hình từ `backend/.env`; biến môi trường đặt lúc chạy được ưu tiên hơn file.
Mẫu đủ các biến: [`.env.example`](.env.example). Key chỉ để trong `.env` (đã nằm trong `.gitignore`).

| `LLM_PROVIDER` | Dùng khi | Biến cần điền |
|---|---|---|
| `mock` (mặc định) | Chạy thử giao diện / luồng, không cần key (không suy luận) | — |
| `bedrock` | Bản đích theo báo cáo: Claude trên Amazon Bedrock | `BEDROCK_MODEL_ID`, `BEDROCK_REGION`, credentials tài khoản nền tảng |
| `anthropic` | Key Claude API (`sk-ant-…`) | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| `anthropic` + gateway | Key `sk-…` của một **gateway định dạng Anthropic** — loại được hướng dẫn cấu hình cho Claude Code bằng `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` (có thể chạy model khác phía sau) | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL` |
| `openai` | Máy chủ **định dạng OpenAI** (`/v1/chat/completions`): Ollama local, OpenAI, gateway tương thích | `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_KEY` (mục Ollama bên dưới) |
| `mcp` | Một MCP client (ví dụ Claude Code) đóng vai LLM | — (xem `../infra/localstack/README.md`) |

Key thuộc loại nào: xem hướng dẫn của bên cấp key. Họ bảo đặt `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`
→ dòng *anthropic + gateway*; họ đưa "OpenAI base URL" → dòng `openai`.

### Gateway định dạng Anthropic

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_BASE_URL=https://gateway.example.com   # URL bên cấp key đưa, không thêm /v1
ANTHROPIC_AUTH_TOKEN=sk-...                      # key của bạn
ANTHROPIC_MODEL=<tên model gateway liệt kê>
ANTHROPIC_GATEWAY_CACHE=true                     # tuỳ chọn, xem dưới
```

- Có `ANTHROPIC_BASE_URL` thì provider chạy **chế độ tương thích** (`app/llm/anthropic.py`): chỉ gửi request
  Messages API cơ bản (model, system, messages, tools, max_tokens), xác thực `Authorization: Bearer`, không gửi
  thinking / `LLM_EFFORT` / beta riêng của Claude — gateway chạy model khác thường từ chối các tham số đó.
- `ANTHROPIC_GATEWAY_CACHE=true` gắn `cache_control` vào system prompt, tool cuối và tin nhắn mới nhất. Mỗi vòng
  của agent gửi lại toàn bộ prompt + bộ tool + hội thoại; gateway có tính giá "cache read" sẽ tính phần lặp lại
  này rẻ hơn. Kiểm tra trong log backend: `cache_read=…` lớn hơn 0 từ vòng thứ hai.
- Kiểm tra nhanh key và model:
  ```bash
  curl -s $ANTHROPIC_BASE_URL/v1/messages -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
    -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
    -d '{"model":"<model>","max_tokens":50,"messages":[{"role":"user","content":"hi"}]}'
  ```
- Đã chạy thật (2026-11-10/11) với một gateway phục vụ model Gemini, dữ liệu từ LocalStack: KB1 và KB2 chẩn đoán
  đúng, đề xuất sửa được duyệt và kiểm chứng đạt. Một câu hỏi tốn khoảng 150–300 nghìn token đầu vào (4–8 vòng);
  model chia nhỏ nhiều vòng có thể chạm `MAX_TURN_TOKENS` (mặc định 200.000) — nâng lên nếu cần.

Lưu ý khi dùng gateway hoặc máy chủ bên thứ ba (cả `anthropic` + gateway lẫn `openai`):

- Model **phải gọi được tool**: agent gọi các tool đọc AWS và kết thúc bằng tool `submit_diagnosis`.
- **Dữ liệu đi qua máy chủ đó**: câu hỏi và kết quả đọc AWS (đã qua sanitizer nhưng vẫn có tên tài nguyên, IP,
  cấu hình, log). Chỉ dùng với LocalStack hoặc tài khoản test; đây là đường thay thế cho demo, bản đích là Bedrock.
- Header của web hiện tên provider (`LLM: anthropic` / `openai`); khi demo nên nói rõ LLM đang chạy qua bên thứ ba.

## Chat với model local qua Ollama

Provider `openai` dùng Chat Completions và function calling qua HTTP async, tương thích
[Ollama](https://docs.ollama.com/api/openai-compatibility). Model cần hỗ trợ tool calling;
[Qwen2.5](https://ollama.com/library/qwen2.5) có hỗ trợ. Provider này gọi endpoint đã cấu
hình; tên `openai` không có nghĩa request được gửi tới dịch vụ OpenAI.

Kiểm tra Ollama đang chạy và lấy đúng tên model:

```bash
ollama list
curl http://localhost:11434/v1/models
```

Với Qwen local, tạo biến thể context 16.384 token từ thư mục gốc repo:

```bash
ollama create autoaws-qwen2.5:16k -f infra/ollama/Modelfile
```

Biến thể dùng lại trọng số `qwen2.5:latest`, đặt temperature 0.2. Khi thử trên máy dev,
context 4.096 không giữ được đầy đủ prompt và bộ tool (khoảng 5–6 nghìn token trước khi có lịch sử), khiến
model bỏ qua chỉ thị ngay cả với lời chào. Tăng `OPENAI_MAX_TOKENS` chỉ tăng giới hạn
đầu ra; context đầu vào được đặt bằng `num_ctx` trong Modelfile. Context 16.384 vẫn
cần đủ chỗ cho lịch sử, kết quả tool và đầu ra; đây không phải bảo đảm chất lượng mọi lượt.

Sửa hoặc thêm các dòng sau trong **`backend/.env` hiện có**:

```dotenv
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=autoaws-qwen2.5:16k
OPENAI_API_KEY=
OPENAI_TIMEOUT_SECONDS=120
OPENAI_MAX_TOKENS=4096
OPENAI_TOKEN_LIMIT_FIELD=max_tokens
```

`OPENAI_MODEL` phải khớp tên trong `ollama list`; đổi hostname nếu Ollama nằm trên máy
khác. URL gồm `/v1`, provider tự nối `/chat/completions`. Local Ollama không cần API key;
server có xác thực dùng `OPENAI_API_KEY`. Một số server yêu cầu trường giới hạn token
`max_completion_tokens`: đặt `OPENAI_TOKEN_LIMIT_FIELD=max_completion_tokens`.

Khởi động lại backend sau khi sửa `.env`, kể cả khi dùng `--reload`:

```bash
cd backend
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m uvicorn app.main:app --reload
```

Chạy frontend với `VITE_USE_MOCK=false` (hoặc bỏ biến này), mở Chat trên kết nối AWS đã
verify và hỏi bằng tiếng Việt. Timeline hiển thị các tool đọc AWS; model trả kết luận
qua `submit_diagnosis`, server kiểm bằng chứng và lưu lịch sử như các provider khác.
Đây là chat chẩn đoán AWS: vẫn cần kết nối AWS đã verify. Ollama thay phần suy luận LLM,
không thay DynamoDB, Cognito hay quyền AWS của backend. Không cần quyền Bedrock để gọi Ollama.

Backend trong Docker truy cập Ollama trên host bằng
`OPENAI_BASE_URL=http://host.docker.internal:11434/v1`. Trên Linux, thêm vào service
`backend` trong file Compose đang dùng:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Ollama phải lắng nghe trên địa chỉ mà Docker truy cập được; cấu hình `OLLAMA_HOST` cho
tiến trình/dịch vụ Ollama nếu cần. `localhost` trong container là container đó.

Timeout: kiểm tra tài nguyên máy và tăng `OPENAI_TIMEOUT_SECONDS` nếu model tải chậm.
`MAX_AGENT_SECONDS` mặc định 240 giây áp dụng cho toàn lượt chẩn đoán; tăng riêng nếu
model local cần nhiều thời gian qua nhiều vòng. Phản hồi bị cắt hoặc tool arguments sai
JSON sẽ bị từ chối; có thể tăng `OPENAI_MAX_TOKENS` nếu thiếu token. Model nhỏ có thể
bỏ sót lớp kiểm tra hoặc gọi lặp tool: tích hợp thành công chưa xác nhận độ chính xác
chẩn đoán. Backend không tự đổi sang provider khác khi endpoint lỗi.

Đã smoke test Ollama thật với `qwen2.5:latest` (2026-11-10): model chọn đúng
`describe_instances` từ registry, nhận kết quả mô phỏng rồi gọi `submit_diagnosis` với
arguments hợp lệ theo `DiagnosisAnswer`. Test không gọi AWS thật. Bộ test HTTP giả lập
kiểm tra thêm luồng job, che secret, kiểm bằng chứng, từ chối tool không đăng ký và giới
hạn vòng lặp; chưa đánh giá độ chính xác Qwen trên các kịch bản AWS thật.

## Deploy backend trên EC2

Frontend build riêng và phục vụ từ S3 qua CloudFront. Trên EC2 đã cài Docker Engine
và Compose plugin, tạo bảng bằng [`infra/cloudformation/dynamodb.yaml`](../infra/cloudformation/dynamodb.yaml)
và điền cấu hình theo [hướng dẫn DynamoDB](../infra/cloudformation/README.md), rồi chạy từ thư mục gốc repo:

```bash
# Chỉ copy nếu chưa có backend/.env; sau đó chỉnh provider, region và cấu hình AWS.
cp -n backend/.env.example backend/.env
nano backend/.env

docker compose -f docker-compose.backend.yml up -d --build
docker compose -f docker-compose.backend.yml ps
docker compose -f docker-compose.backend.yml logs -f backend
curl http://localhost:8000/api/health
```

`docker-compose.backend.yml` chỉ chạy backend, không build hay chạy frontend. File này
truyền `backend/.env` vào container, đặt `RUNTIME=local`, `CORS_ORIGINS=*`,
`STORAGE_BACKEND=dynamodb`, `DYNAMODB_CREATE_TABLE=false` (ghi đè các biến tương ứng
trong `.env`). Backend tự khởi
động lại khi tiến trình thoát hoặc Docker khởi động lại, có healthcheck và giới hạn
log Docker. Healthcheck chỉ kiểm tra API còn phản hồi, không kiểm tra AWS/LLM và
không tự restart container chỉ vì trạng thái `unhealthy`.

Dữ liệu nằm trong DynamoDB của tài khoản nền tảng; không cần volume database trên EC2.
`.env` nằm ngoài image và không được commit.

File Compose này không mount `~/.aws` từ máy host. Nếu dùng named profile, cần tự
mount thư mục credentials chỉ đọc; nếu dùng IAM role của EC2, để trống
`PLATFORM_AWS_PROFILE` và bảo đảm container truy cập được instance metadata.

Cổng `8000` phục vụ HTTP. Để frontend CloudFront gọi API trực tiếp, cần đặt HTTPS
trước backend, ví dụ reverse proxy trên EC2 hoặc ALB, rồi build frontend với
`VITE_API_URL=https://api.example.com` (xem `../frontend/README.md`). Không dùng
`http://<EC2-IP>:8000` làm API URL cho trang HTTPS: trình duyệt chặn mixed content
dù CORS là `*` ([MDN](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Mixed_content)).
File Compose không cấu hình TLS, DNS hay Security Group.
Trước khi mở API cho người dùng, đặt `AUTH_MODE=cognito`, `COGNITO_USER_POOL_ID`,
`COGNITO_CLIENT_ID`, `COGNITO_DOMAIN` và `EXTERNAL_ID_SECRET` (khoá ký External ID; thiếu thì
backend không khởi động; giữ cố định, đổi khoá làm mọi External ID đã cấp mà chưa dùng mất hiệu lực)
theo stack Auth hiện có (xem README gốc, mục
chạy local với Cognito thật). Cơ chế auth và phân vùng người dùng giữ nguyên từ `main`.
Với bản EC2 không dùng CDK, có thể tạo stack Cognito độc lập bằng
[`cognito.yaml`](../infra/cloudformation/cognito.yaml); xem
[`hướng dẫn cấu hình và kiểm tra đăng nhập`](../infra/cloudformation/COGNITO.md).

`docker-compose.yml` ở thư mục gốc vẫn dùng cho phát triển local cả backend và frontend.

## Test / lint

```bash
pytest            # AWS được giả lập bằng moto, không cần tài khoản thật
ruff check app tests && ruff format app tests
```

## Thử nhanh bằng curl

```bash
# tạo kết nối bằng access key (chỉ dùng cho môi trường học tập)
curl -s localhost:8000/api/connections -H 'content-type: application/json' -d '{
  "type":"access_key","name":"lab","region":"ap-southeast-1",
  "access_key_id":"AKIA...","secret_access_key":"..."}'
curl -s -X POST localhost:8000/api/connections/<id>/verify
curl -s localhost:8000/api/conversations -H 'content-type: application/json' -d '{"connection_id":"<id>"}'
# gửi câu hỏi → 202 + job; hỏi lại job tới khi xong (API_CONTRACT §3, §8)
curl -s localhost:8000/api/conversations/<conv_id>/messages -H 'content-type: application/json' \
  -d '{"content":"Tôi không SSH được vào instance web-server"}'
curl -s "localhost:8000/api/jobs/<job_id>?after=-1"     # events: status, tool_call, tool_result, answer, done
curl -s localhost:8000/api/proposals                    # đề xuất khắc phục chờ duyệt
```

## Cấu trúc

| Thư mục | Vai trò |
|---|---|
| `app/api/` | Router REST: connections, conversations, jobs, proposals, tools |
| `app/agent/` | Vòng lặp agent, prompt, schema câu trả lời, kiểm tra bằng chứng |
| `app/aws/tools/` | 19 công cụ **đọc** (registry chỉ nhận action đọc, guard botocore chặn ghi lúc chạy) |
| `app/aws/remediation/` | **Nơi duy nhất ghi**: danh mục 6 hành động + session ghi khoá theo hành động |
| `app/remediation/` | Vòng đời đề xuất: duyệt / từ chối / góp ý / hết hạn / kiểm tra lại / thực thi / kiểm chứng |
| `app/llm/` | Provider: mock, openai (Ollama/Chat Completions), bedrock + anthropic (`claude.py`), mcp (MCP client đóng vai LLM) |
| `app/worker.py`, `app/handlers/`, `app/platform/` | Việc chạy nền (job chẩn đoán, verify), Lambda handler, điều phối `RUNTIME=local\|lambda` |
| `app/storage/` | `Store`: SQLite hoặc DynamoDB (một bảng) |

## Chế độ chạy

- `RUNTIME=local` (mặc định): job và luồng duyệt chạy nền trong tiến trình FastAPI.
- `RUNTIME=lambda`: cùng mã nguồn, chạy dưới dạng Lambda `api-handler` / `agent-worker` / `action-executor` + Step Functions (`infra/cdk/`). Biến môi trường do stack CDK đặt.

## Lưu ý bảo mật

- Access key của kết nối `access_key` lưu **plaintext trong SQLite** (`DB_PATH`) hoặc trong item DynamoDB — chỉ dùng dev/học tập. Kiểu `role` (AssumeRole + ExternalId) là đường chuẩn; credentials tạm thời chỉ nằm trong bộ nhớ.
- Mọi tool chỉ gọi API đọc; `app/aws/registry.py` từ chối đăng ký action ghi. Lệnh ghi chỉ có trong `app/aws/remediation/`, chạy sau khi người dùng duyệt, bằng role `AutoAWSRemediation` (access key chỉ khi `REMEDIATION_ALLOW_ACCESS_KEYS=true`).
- Xác thực (`docs/API_CONTRACT.md` §0.1): `AUTH_MODE=none` (mặc định) = một người dùng `local`, **đừng mở API ra mạng ngoài**; `AUTH_MODE=cognito` = mọi route trừ `/api/health`, `/api/auth/config` cần access token Cognito (`app/auth.py`: trên Lambda đọc claims JWT authorizer đã kiểm, ngoài Lambda tự kiểm chữ ký qua JWKS; luôn kiểm issuer / `token_use=access` / `client_id`). Connection, conversation, job, proposal có `user_id`; tài nguyên của người khác trả 404. ExternalId do server sinh.
- Dữ liệu AWS đi qua `app/sanitizer.py` trước khi tới LLM và trước khi lưu `output_summary`.

## Lưu trữ: DynamoDB

`STORAGE_BACKEND=dynamodb` là mặc định. Bảng `DYNAMODB_TABLE` trong tài khoản nền tảng
được tạo trước bằng [CloudFormation](../infra/cloudformation/README.md).
Điền `DYNAMODB_REGION`, để trống `DYNAMODB_ENDPOINT_URL` khi dùng endpoint AWS chuẩn
hoặc điền URL tuỳ chọn; giữ `DYNAMODB_CREATE_TABLE=false` khi dùng bảng đã tạo.
Backend kiểm tra bảng bằng `DescribeTable` khi khởi động, không tự fallback sang SQLite.
Khi chạy uvicorn từ `backend/`, app nạp `.env` vào môi trường để boto3 cũng đọc được
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` và `AWS_SESSION_TOKEN` (nếu dùng credentials
tạm thời). Biến đã có trong môi trường tiến trình được ưu tiên hơn `.env`.
Router và agent loop dùng interface `app/storage/base.py::Store`.
SQLite còn là tuỳ chọn tường minh cho test/local (`STORAGE_BACKEND=sqlite`, `DB_PATH`),
không được dùng trong hai file Compose. Không có bước tự chuyển dữ liệu SQLite cũ.

Thiết kế bảng DynamoDB (một bảng):

| Item | PK / SK | GSI1 |
|---|---|---|
| Kết nối | `CONN#<id>` / `META` | `CONNECTIONS#<user_id>` / `<created_at>#<id>` |
| Hội thoại | `CONV#<id>` / `META` | `CONVS#<connection_id>` / `<updated_at>#<id>` |
| Tin nhắn | `CONV#<conversation_id>` / `MSG#<created_at>#<id>` (tool call nhúng trong item) | — |
| Đề xuất khắc phục | `PROP#<id>` / `META` | `PROPOSALS#<user_id>` / `<created_at>#<id>` |
| Job chẩn đoán | `JOB#<id>` / `META` (thuộc tính `ttl`) | `JOBS#<conversation_id>` / `<created_at>#<id>` |

Index `ById` (theo `id`) để lấy tool call của một tin nhắn. Chạy thử với LocalStack:

```bash
DYNAMODB_TABLE=autoaws DYNAMODB_REGION=ap-southeast-1 \
DYNAMODB_CREATE_TABLE=true DYNAMODB_ENDPOINT_URL=http://localhost:4566 uvicorn app.main:app
```

Lưu ý: GSI nhất quán sau (eventually consistent) — danh sách ngay sau khi ghi có thể trễ vài ms; secret của kết nối access key vẫn nằm trong item (bảng đã mã hoá KMS, nhưng ai đọc được bảng là đọc được secret — cần mã hoá cấp trường trước khi có nhiều người dùng).

## Thêm tool AWS mới

1. Viết hàm `fn(session, params) -> dict` trong `app/aws/tools/<group>.py`, gắn `@tool(...)` với `aws_actions` chính xác.
2. Thêm test moto trong `tests/test_tools.py`.
3. Thêm dòng vào bảng cuối `docs/API_CONTRACT.md`.

Template CloudFormation (`GET /api/connections/{id}/cloudformation`) tự sinh IAM policy từ `aws_actions` của mọi tool.
