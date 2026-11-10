# AutoAWS backend

FastAPI + boto3. Thiết kế chi tiết: `../docs/BACKEND_PLAN.md`; hợp đồng API: `../docs/API_CONTRACT.md`.

## Chạy

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # LLM_PROVIDER=mock chạy được ngay, không cần key
uvicorn app.main:app --reload # http://localhost:8000/docs
```

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

## Lưu trữ: SQLite hoặc DynamoDB

`STORAGE_BACKEND=sqlite` (mặc định, file `DB_PATH`) hoặc `dynamodb` (bảng `DYNAMODB_TABLE` trong tài khoản nền tảng, mã hoá KMS). Router và agent loop chỉ dùng interface `app/storage/base.py::Store`; hai bản cài đặt `sql.py` và `dynamo.py` qua cùng bộ test `tests/test_store.py`.

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
STORAGE_BACKEND=dynamodb DYNAMODB_ENDPOINT_URL=http://localhost:4566 uvicorn app.main:app
```

Lưu ý: GSI nhất quán sau (eventually consistent) — danh sách ngay sau khi ghi có thể trễ vài ms; secret của kết nối access key vẫn nằm trong item (bảng đã mã hoá KMS, nhưng ai đọc được bảng là đọc được secret — cần mã hoá cấp trường trước khi có nhiều người dùng).

## Thêm tool AWS mới

1. Viết hàm `fn(session, params) -> dict` trong `app/aws/tools/<group>.py`, gắn `@tool(...)` với `aws_actions` chính xác.
2. Thêm test moto trong `tests/test_tools.py`.
3. Thêm dòng vào bảng cuối `docs/API_CONTRACT.md`.

Template CloudFormation (`GET /api/connections/{id}/cloudformation`) tự sinh IAM policy từ `aws_actions` của mọi tool.
