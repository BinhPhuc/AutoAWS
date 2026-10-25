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

## LLM ưu tiên: OpenAI-compatible / Ollama

`LLM_PROVIDER=openai` gọi **Chat Completions + function calling** qua HTTP async. Endpoint
có thể là Ollama tự host hoặc dịch vụ khác tương thích giao thức này; model cần hỗ trợ
tool calling. Cấu hình model ở backend, không liên quan region tài nguyên trên trang Connect.
`mock` vẫn là mặc định để chạy pipeline khi chưa có model server.

Với Ollama đã cài, khởi động server nếu chưa chạy và tải model có tool calling, ví dụ:

```bash
ollama serve
# Trong terminal khác; chọn model phù hợp RAM/VRAM của máy.
ollama pull qwen3:8b
ollama list
curl http://localhost:11434/v1/models
```

Sửa hoặc thêm các dòng sau trong **`backend/.env` hiện có** (giữ các credentials AWS):

```dotenv
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen3:8b
OPENAI_API_KEY=
OPENAI_TIMEOUT_SECONDS=120
OPENAI_MAX_TOKENS=4096
OPENAI_TOKEN_LIMIT_FIELD=max_tokens
MAX_AGENT_ITERATIONS=10
AGENT_DEMO_MODE=false
```

`OPENAI_MODEL` phải khớp tên trong `ollama list`. Local Ollama không yêu cầu API key.
Nếu server ở máy khác, thay hostname trong `OPENAI_BASE_URL`; nếu server có xác thực,
điền `OPENAI_API_KEY`. URL là **API base URL**, gồm tiền tố như `/v1`, không thêm
`/chat/completions` vì provider tự nối đường dẫn này. Với model yêu cầu trường giới hạn
token mới của OpenAI, đặt `OPENAI_TOKEN_LIMIT_FIELD=max_completion_tokens`.

Khởi động lại backend sau khi sửa `.env` (kể cả dùng `--reload`). Mở Chat trên kết nối AWS
đã verify và hỏi “Liệt kê các EC2 instance trong region này”. Timeline sẽ hiển thị tool
AWS thật; kết quả vẫn qua sanitizer và trả lời theo cấu trúc tiếng Việt. AWS credentials
trong `.env` vẫn cần cho AssumeRole; inference qua Ollama không cần quyền Bedrock.

Để chỉ thử model gọi một tool giả, đặt `AGENT_DEMO_MODE=true` và hỏi “Kiểm tra trạng thái
instance demo”. Model được yêu cầu gọi `demo_instance_status` rồi trả lời rằng dữ liệu
được mô phỏng. Mỗi lượt gọi model, kể cả sửa JSON, đều tính vào giới hạn tối đa 10 vòng.

Backend chạy trong Docker, Ollama chạy trên host: đặt
`OPENAI_BASE_URL=http://host.docker.internal:11434/v1`, rồi chạy
`docker compose up -d --build --force-recreate backend`. Compose đã thêm ánh xạ host cho
Linux. Ollama cần lắng nghe trên interface Docker truy cập được (cấu hình `OLLAMA_HOST`
cho tiến trình/dịch vụ Ollama); địa chỉ loopback mặc định chỉ dùng được từ host.

Lỗi HTTP 401/403: kiểm tra API key/quyền model; 404: kiểm tra URL và tên model đã tải;
400: kiểm tra model hỗ trợ tools và trường giới hạn token; timeout: kiểm tra server,
tài nguyên máy và tăng `OPENAI_TIMEOUT_SECONDS` khi model tải chậm. Phản hồi bị cắt
sẽ không được dùng để thực thi tool; tăng `OPENAI_MAX_TOKENS` nếu model cần thêm token.
Chi tiết lỗi từ server không được đưa vào SSE để tránh lộ keys hoặc nội dung request.
Backend không tự chuyển provider khi gặp lỗi; đổi `LLM_PROVIDER` rõ ràng để chọn nơi
gửi dữ liệu. Bedrock vẫn dùng được bằng `LLM_PROVIDER=bedrock` với cấu hình riêng bên dưới.

Tham chiếu giao thức: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling),
[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility),
[Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling).

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
