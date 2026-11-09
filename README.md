# AutoAWS

**Trợ lý AI chẩn đoán và khắc phục sự cố trên môi trường AWS.**
Đồ án môn Điện toán đám mây — Nhóm 16, Trường ĐH Công nghệ, ĐHQGHN.

Người dùng kết nối tài khoản AWS của mình bằng **quyền chỉ đọc**, rồi mô tả sự cố bằng ngôn ngữ tự nhiên ("Website báo 502 từ chiều nay"). Agent lập kế hoạch kiểm tra, gọi các **công cụ đọc AWS** để lấy dữ liệu thật (cấu hình, log, chỉ số, lịch sử thay đổi), đối chiếu theo đường đi của kết nối (DNS → IP → route table → NACL → Security Group → Load Balancer → instance → ứng dụng) và trả lời có cấu trúc:

> **Nguyên nhân** → **Bằng chứng** (trích từ dữ liệu đã đọc) → **Cách khắc phục** → **Những điểm chưa xác nhận được** (kèm lệnh để tự kiểm tra)

## Tính năng

| Tính năng (báo cáo §1.1) | Trạng thái |
|---|---|
| **Chẩn đoán qua hỏi đáp** | ✅ 19 công cụ đọc (EC2, SSM, VPC, Route 53, DNS công khai, ELB, CloudWatch metrics/alarms, Logs Insights, CloudTrail); câu trả lời nhiều nguyên nhân gốc, server tự kiểm từng bằng chứng; giới hạn vòng / thời gian / token; chống prompt injection qua dữ liệu |
| **Khắc phục có phê duyệt** (human-in-the-loop) | ✅ 6 hành động cố định (Bảng 2.11), xem trước → Duyệt / Từ chối / Góp ý → kiểm tra lại → thực thi bằng role riêng → kiểm chứng → đề xuất hoàn tác |
| Kiểm tra theo checklist | ⏳ chưa làm |
| Đăng nhập (Cognito) | ⏳ chưa làm — hiện chế độ 1 người dùng |

## Kiến trúc

Cùng một mã nguồn chạy ở hai chế độ (`RUNTIME`):

**`RUNTIME=local`** — một tiến trình FastAPI, dùng để phát triển và demo:
```
Frontend (React/Vite) ──REST + job polling──► Backend FastAPI
                                              ├─ Agent loop ──► LLM provider (mock | bedrock | anthropic | mcp)
                                              ├─ Tool đọc AWS ──► Sanitizer
                                              ├─ Luồng duyệt khắc phục (chạy nền)
                                              └─ SQLite | DynamoDB
                                                    │ boto3: AssumeRole + ExternalId (hoặc Access Key cho dev)
                                                    ▼
                                    Tài khoản AWS của người dùng (role chỉ đọc · role sửa tuỳ chọn)
```

**`RUNTIME=lambda`** — serverless đúng báo cáo §2.2, hạ tầng CDK trong [`infra/cdk/`](infra/cdk/README.md):
```
CloudFront ─┬─ S3 (giao diện)
            └─ /api/* ─► API Gateway ─► Lambda api-handler ──invoke──► Lambda agent-worker ─► Bedrock
                                                                          │ AssumeRole AutoAWSReadOnly
                         Step Functions remediation-flow ◄─StartExecution─┘
                           SNS email → chờ duyệt (24 h) → kiểm tra lại → Lambda action-executor
                                                                          │ AssumeRole AutoAWSRemediation
                         DynamoDB (KMS, PITR, TTL) · CloudWatch alarms · Budgets
```
Agent-worker (thành phần duy nhất nói chuyện với LLM) **không bao giờ** có quyền ghi; chỉ action-executor ghi, và chỉ đề xuất đã được duyệt.

## Trạng thái

- Chạy end-to-end trên máy với LLM giả lập (`LLM_PROVIDER=mock`), hoặc một MCP client đóng vai LLM (`LLM_PROVIDER=mcp`), dữ liệu AWS từ LocalStack.
- `BedrockProvider` (Claude qua Bedrock Mantle) và hạ tầng CDK **đã viết, chưa chạy trên AWS thật** (chưa có tài khoản).
- Kiểm thử: 190 test backend (moto), 7 test frontend, 7 test CDK. Chi tiết ở [`AGENTS.md`](AGENTS.md) mục "Trạng thái hiện tại".

## Tài liệu

| File | Nội dung |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Hướng dẫn cho AI coding agent & người mới: trạng thái, bố cục, cách chạy, ràng buộc |
| [`docs/SYSTEM_OVERVIEW.md`](docs/SYSTEM_OVERVIEW.md) | Hệ thống làm gì (tóm tắt `AutoAWS.docx`) |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | Hợp đồng API giữa frontend và backend |
| [`docs/BACKEND_PLAN.md`](docs/BACKEND_PLAN.md) | Kế hoạch backend (FastAPI) |
| [`docs/FRONTEND_PLAN.md`](docs/FRONTEND_PLAN.md) | Kế hoạch frontend (React) |
| [`infra/cdk/README.md`](infra/cdk/README.md) | Hạ tầng nền tảng serverless (CDK): stack, quyền, cách deploy |
| [`infra/localstack/README.md`](infra/localstack/README.md) | Kịch bản sự cố trên LocalStack + chấm điểm `infra/eval/run_eval.py` |
| [`infra/aws-scenarios/README.md`](infra/aws-scenarios/README.md) | Kịch bản KB1–KB7 trên AWS thật (CloudFormation) |
| [`infra/demo-apps/README.md`](infra/demo-apps/README.md) | App giả lập cho KB3, KB7 (chạy cả local lẫn EC2) |

## Quick start

```bash
# 1. Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cp .env.example .env
uvicorn app.main:app --reload          # http://localhost:8000/docs

# 2. Frontend (terminal khác)
cd frontend && pnpm install && cp .env.example .env && pnpm dev   # http://localhost:5173

# Hoặc Docker: cp backend/.env.example backend/.env && docker compose up --build
```

Mở http://localhost:5173 → **Connections** → Add connection (Access Key cho dev, hoặc IAM Role + template CloudFormation) → Verify → **Diagnose** → mô tả sự cố. Đề xuất sửa (nếu có) hiện ngay trong câu trả lời và ở trang **Proposals**; với Access Key cần bật `REMEDIATION_ALLOW_ACCESS_KEYS=true` (chỉ dev).
Không có backend? `VITE_USE_MOCK=true pnpm dev` chạy với dữ liệu giả lập.
Không có AWS / Bedrock? Xem `infra/localstack/README.md`: dựng kịch bản trong LocalStack và để một MCP client (ví dụ Claude Code) đóng vai LLM qua `LLM_PROVIDER=mcp`.
Triển khai lên AWS: [`infra/cdk/README.md`](infra/cdk/README.md) (`./build_lambda.sh` rồi `cdk deploy --all`).

## Nhóm

| | Thành viên | Phụ trách |
|---|---|---|
| TV1 | Trần Phúc Khánh | Lõi agent, tri thức chẩn đoán |
| TV2 | Phạm Phúc Bình | Bộ công cụ đọc AWS |
| TV3 | Dương Đình Minh (nhóm trưởng) | Hạ tầng, API, kiểm thử, tài liệu |
| TV4 | Lê Minh Đạt | Checklist, giao diện web |
