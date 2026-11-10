# AutoAWS backend

FastAPI + boto3. Thiết kế chi tiết: `../docs/BACKEND_PLAN.md`; hợp đồng API: `../docs/API_CONTRACT.md`.

## Chạy

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # Điền DYNAMODB_TABLE, DYNAMODB_REGION và credentials nền tảng
uvicorn app.main:app --reload # http://localhost:8000/docs
```

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
| `app/llm/` | Provider: mock, bedrock + anthropic (`claude.py`), mcp (MCP client đóng vai LLM) |
| `app/worker.py`, `app/handlers/`, `app/platform/` | Việc chạy nền (job chẩn đoán, verify), Lambda handler, điều phối `RUNTIME=local\|lambda` |
| `app/storage/` | `Store`: SQLite hoặc DynamoDB (một bảng) |

## Chế độ chạy

- `RUNTIME=local` (mặc định): job và luồng duyệt chạy nền trong tiến trình FastAPI.
- `RUNTIME=lambda`: cùng mã nguồn, chạy dưới dạng Lambda `api-handler` / `agent-worker` / `action-executor` + Step Functions (`infra/cdk/`). Biến môi trường do stack CDK đặt.

## Lưu ý bảo mật

- Access key của kết nối `access_key` lưu **plaintext trong SQLite** (`DB_PATH`) hoặc trong item DynamoDB — chỉ dùng dev/học tập. Kiểu `role` (AssumeRole + ExternalId) là đường chuẩn; credentials tạm thời chỉ nằm trong bộ nhớ.
- Mọi tool chỉ gọi API đọc; `app/aws/registry.py` từ chối đăng ký action ghi. Lệnh ghi chỉ có trong `app/aws/remediation/`, chạy sau khi người dùng duyệt, bằng role `AutoAWSRemediation` (access key chỉ khi `REMEDIATION_ALLOW_ACCESS_KEYS=true`).
- Chưa có xác thực: đừng mở API ra mạng ngoài.
- Dữ liệu AWS đi qua `app/sanitizer.py` trước khi tới LLM và trước khi lưu `output_summary`.

## Lưu trữ: DynamoDB

`STORAGE_BACKEND=dynamodb` là mặc định. Bảng `DYNAMODB_TABLE` trong tài khoản nền tảng
được tạo trước bằng [CloudFormation](../infra/cloudformation/README.md).
Điền `DYNAMODB_REGION`, để trống `DYNAMODB_ENDPOINT_URL` khi dùng endpoint AWS chuẩn
hoặc điền URL tuỳ chọn; giữ `DYNAMODB_CREATE_TABLE=false` khi dùng bảng đã tạo.
Backend kiểm tra bảng bằng `DescribeTable` khi khởi động, không tự fallback sang SQLite.
Router và agent loop dùng interface `app/storage/base.py::Store`.
SQLite còn là tuỳ chọn tường minh cho test/local (`STORAGE_BACKEND=sqlite`, `DB_PATH`),
không được dùng trong hai file Compose. Không có bước tự chuyển dữ liệu SQLite cũ.

Thiết kế bảng DynamoDB (một bảng):

| Item | PK / SK | GSI1 |
|---|---|---|
| Kết nối | `CONN#<id>` / `META` | `CONNECTIONS` / `<created_at>#<id>` |
| Hội thoại | `CONV#<id>` / `META` | `CONVS#<connection_id>` / `<updated_at>#<id>` |
| Tin nhắn | `CONV#<conversation_id>` / `MSG#<created_at>#<id>` (tool call nhúng trong item) | — |
| Đề xuất khắc phục | `PROP#<id>` / `META` | `PROPOSALS` / `<created_at>#<id>` |
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

## Đăng nhập Cognito

Xem [cấu hình Cognito, cách ly `user_id` và migration dữ liệu cũ](../docs/AUTH.md). Mặc định `AUTH_MODE=cognito`; EC2 cần `COGNITO_ISSUER`, `COGNITO_CLIENT_ID`, `COGNITO_DOMAIN`. Dev offline đặt `AUTH_MODE=none` cùng `APP_ENV=dev`, `RUNTIME=local`. Frontend lấy cấu hình công khai từ API, không cần biến Vite riêng cho Cognito.
