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
curl -N localhost:8000/api/conversations/<conv_id>/messages -H 'content-type: application/json' \
  -d '{"content":"Tôi không SSH được vào instance web-server"}'
```

## Lưu ý bảo mật (bản init)

- Access key của kết nối `access_key` lưu **plaintext trong SQLite** (`DB_PATH`) hoặc trong item DynamoDB — chỉ dùng dev/học tập. Kiểu `role` (AssumeRole + ExternalId) là đường chuẩn; credentials tạm thời chỉ nằm trong bộ nhớ.
- Mọi tool chỉ gọi API đọc; `app/aws/registry.py` từ chối đăng ký action ghi.
- Dữ liệu AWS đi qua `app/sanitizer.py` trước khi tới LLM và trước khi lưu `output_summary`.

## Lưu trữ: SQLite hoặc DynamoDB

`STORAGE_BACKEND=sqlite` (mặc định, file `DB_PATH`) hoặc `dynamodb` (bảng `DYNAMODB_TABLE` trong tài khoản nền tảng, mã hoá KMS). Router và agent loop chỉ dùng interface `app/storage/base.py::Store`; hai bản cài đặt `sql.py` và `dynamo.py` qua cùng bộ test `tests/test_store.py`.

Thiết kế bảng DynamoDB (một bảng):

| Item | PK / SK | GSI1 |
|---|---|---|
| Kết nối | `CONN#<id>` / `META` | `CONNECTIONS` / `<created_at>#<id>` |
| Hội thoại | `CONV#<id>` / `META` | `CONVS#<connection_id>` / `<updated_at>#<id>` |
| Tin nhắn | `CONV#<conversation_id>` / `MSG#<created_at>#<id>` (tool call nhúng trong item) | — |

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
