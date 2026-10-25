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

- Access key của kết nối `access_key` lưu **plaintext trong SQLite** (`DB_PATH`) — chỉ dùng dev/học tập. Kiểu `role` (AssumeRole + ExternalId) là đường chuẩn; credentials tạm thời chỉ nằm trong bộ nhớ.
- Mọi tool chỉ gọi API đọc; `app/aws/registry.py` từ chối đăng ký action ghi.
- Dữ liệu AWS đi qua `app/sanitizer.py` trước khi tới LLM và trước khi lưu `output_summary`.

## Thêm tool AWS mới

1. Viết hàm `fn(session, params) -> dict` trong `app/aws/tools/<group>.py`, gắn `@tool(...)` với `aws_actions` chính xác.
2. Thêm test moto trong `tests/test_tools.py`.
3. Thêm dòng vào bảng cuối `docs/API_CONTRACT.md`.

Template CloudFormation (`GET /api/connections/{id}/cloudformation`) tự sinh IAM policy từ `aws_actions` của mọi tool.

## Demo Bedrock Converse qua UI (local)

Cấu hình trong `backend/.env` (không commit file này):

```dotenv
LLM_PROVIDER=bedrock
BEDROCK_MODEL_ID=<model ID hoặc inference profile ID hỗ trợ Converse tool use>
BEDROCK_REGION=<region của model>
MAX_AGENT_ITERATIONS=10
AGENT_DEMO_MODE=true
```

Credentials cho AssumeRole và Bedrock đọc trực tiếp từ `backend/.env`, không cần AWS CLI
hay profile trên host:

```dotenv
AWS_ACCESS_KEY_ID=<access key của identity chạy AutoAWS>
AWS_SECRET_ACCESS_KEY=<secret tương ứng>
AWS_SESSION_TOKEN=
AWS_DEFAULT_REGION=ap-southeast-1
PLATFORM_AWS_PROFILE=
PLATFORM_AWS_ACCOUNT_ID=<12 chữ số account AWS chạy AutoAWS>
```

Nếu dùng credentials tạm thời (STS/AWS Academy), điền thêm `AWS_SESSION_TOKEN`; IAM user key
thông thường để trống token. Identity này cần `sts:AssumeRole` trên role đích và
`bedrock:InvokeModel` cho model/inference profile đã chọn. Role đích cần trust policy có
External ID khớp trang Connect và policy đọc tài nguyên.

Cặp access key/secret được truyền trực tiếp vào boto3; credentials có cấu hình được ưu tiên
trước `PLATFORM_AWS_PROFILE`. Thiếu một trong hai trường sẽ báo lỗi, không dùng credential
khác thay thế. Nếu để trống cả credentials, vẫn hỗ trợ profile/default chain như trước.
Biến môi trường của process được Pydantic ưu tiên trước giá trị trong `.env`.
File `.env` được tìm theo thư mục backend, không phụ thuộc thư mục chạy lệnh; sau khi sửa
cấu hình cần khởi động lại backend. Không gửi credentials trong chat/log hoặc commit `.env`.

`PLATFORM_AWS_ACCOUNT_ID` giúp UI điền sẵn trust policy khi người dùng tạo role. Nếu chưa
cấu hình đúng 12 chữ số, UI báo phần thiết lập kết nối tạm thời chưa sẵn sàng; không xuất
trust policy có placeholder. Account ID là thông tin công khai, không phải credentials.

Docker Compose cũng đọc `backend/.env`; không cần mount thư mục `~/.aws` của host.
Để chẩn đoán AWS thật, đặt `AGENT_DEMO_MODE=false`; frontend dùng `VITE_USE_MOCK=false`.

Chạy backend bằng `uvicorn app.main:app --reload`, frontend bằng `pnpm dev` với
`VITE_USE_MOCK=false`. Kết nối và xác thực tài khoản AWS như bình thường, mở Chat, nhập:
“Kiểm tra trạng thái instance demo và giải thích kết quả mô phỏng.”

Kết quả mong đợi: timeline gọi `demo_instance_status` một lần, sau đó DiagnosisCard trả lời
bằng tiếng Việt rằng instance **mô phỏng** đang `stopped`; trạng thái AWS thật chưa xác nhận.
Tool demo không truy cập AWS. Bedrock vẫn là dịch vụ từ xa và cần credentials hợp lệ.
Tắt `AGENT_DEMO_MODE` để quay về danh sách tool đọc AWS thật.

Mỗi lần gọi model tính một vòng, kể cả sửa định dạng JSON. Cấu hình chỉ nhận 1–10;
đạt giới hạn mà chưa kết luận sẽ trả `MAX_ITERATIONS` rồi `done`. Lỗi truy cập Bedrock,
phản hồi rỗng hoặc bị cắt sẽ trả `LLM_UNAVAILABLE`. Kiểm thử tự động dùng Stubber/moto;
smoke test thật cần model/region và quyền AWS của máy chạy.

## Bedrock trả `ValidationException: Operation not allowed`

Nếu request Converse tối giản (không có tools/lịch sử) cũng trả đúng lỗi này, cần kiểm tra
hạn chế truy cập Bedrock ở cấp tài khoản. AWS Knowledge Center mô tả đây là lỗi account
security restriction và hướng dẫn liên hệ AWS Support:
https://repost.aws/knowledge-center/bedrock-invokemodel-api-error

Người vận hành kiểm tra trong account chạy backend: Bedrock Playground ở region/model
đã chọn, trạng thái model access và Service Quotas. Gửi lỗi, model ID, region và Request ID
cho Support để họ xác minh. Không gửi credentials. Không kết luận mọi ValidationException
đều là account restriction; các thông báo khác vẫn có thể là request/model/region sai.

Backend nhận diện riêng thông báo `Operation not allowed`, trả hướng dẫn liên hệ support;
log chỉ ghi lỗi cố định và Request ID, không ghi request/response hay credentials.
`GetFoundationModelAvailability` có thể giúp chẩn đoán nhưng cần quyền đọc riêng;
AccessDenied của lệnh kiểm tra này không chứng minh `InvokeModel` thiếu quyền.
