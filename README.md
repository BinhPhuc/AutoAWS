# AutoAWS

**Trợ lý AI chẩn đoán và khắc phục sự cố trên môi trường AWS.**
Đồ án môn Điện toán đám mây — Nhóm 16, Trường ĐH Công nghệ, ĐHQGHN.

Người dùng kết nối tài khoản AWS của mình bằng **quyền chỉ đọc**, rồi mô tả sự cố bằng ngôn ngữ tự nhiên ("Website báo 502 từ chiều nay"). Agent lập kế hoạch kiểm tra, gọi các **công cụ đọc AWS** để lấy dữ liệu thật (cấu hình, log, chỉ số, lịch sử thay đổi), đối chiếu theo đường đi của kết nối (DNS → IP → route table → NACL → Security Group → Load Balancer → instance → ứng dụng) và trả lời có cấu trúc:

> **Nguyên nhân** → **Bằng chứng** (trích từ dữ liệu đã đọc) → **Cách khắc phục** → **Những điểm chưa xác nhận được** (kèm lệnh để tự kiểm tra)

## Kiến trúc bản init (chạy local)

```
┌─────────────┐  REST + SSE   ┌──────────────────────────────────┐
│  Frontend   │ ────────────► │  Backend (FastAPI)               │
│  React/Vite │ ◄──────────── │  ┌────────────┐  ┌────────────┐ │
└─────────────┘               │  │ Agent loop │─►│ LLM provider│ │  openai (Ollama) | bedrock | mock
                              │  └─────┬──────┘  └────────────┘ │
                              │        │ tool calls (chỉ đọc)    │
                              │  ┌─────▼──────┐  ┌────────────┐ │
                              │  │ AWS tools  │─►│ Sanitizer  │ │
                              │  └─────┬──────┘  └────────────┘ │
                              └────────┼─────────────────────────┘
                                       │ boto3 (Access Key | AssumeRole + ExternalId)
                              ┌────────▼─────────────────────────┐
                              │  Tài khoản AWS của người dùng    │
                              │  EC2 · VPC · Route 53 · ELB ·    │
                              │  CloudWatch · CloudTrail         │
                              └──────────────────────────────────┘
```

Kiến trúc đích (serverless: Cognito, API Gateway, Lambda, Step Functions, DynamoDB, Bedrock) mô tả trong `docs/SYSTEM_OVERVIEW.md` §7.

## Trạng thái

✅ **Init hoàn thành** — chạy end-to-end local với LLM giả lập (`LLM_PROVIDER=mock`), đã triển khai OpenAI-compatible và Bedrock Converse. Ưu tiên `LLM_PROVIDER=openai` để dùng Ollama tự host hoặc API tương thích khác; xem [cấu hình model](backend/README.md#llm-ưu-tiên-openai-compatible--ollama). Inference Ollama thật chưa được smoke test; Bedrock hiện bị hạn chế ở cấp tài khoản. Chưa có: tool CloudWatch/CloudTrail đầy đủ, checklist, đăng nhập. Chi tiết ở `AGENTS.md` mục "Trạng thái hiện tại".

## Tài liệu

| File | Nội dung |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Hướng dẫn cho AI coding agent & người mới: trạng thái, bố cục, cách chạy, ràng buộc |
| [`docs/SYSTEM_OVERVIEW.md`](docs/SYSTEM_OVERVIEW.md) | Hệ thống làm gì (tóm tắt `AutoAWS.docx`) |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | Hợp đồng API giữa frontend và backend |
| [`docs/BACKEND_PLAN.md`](docs/BACKEND_PLAN.md) | Kế hoạch backend (FastAPI) |
| [`docs/FRONTEND_PLAN.md`](docs/FRONTEND_PLAN.md) | Kế hoạch frontend (React) |

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

Mở http://localhost:5173 → **Connections** → Add connection (Access Key cho dev, hoặc IAM Role + template CloudFormation) → Verify → **Diagnose** → mô tả sự cố.
Không có backend? `VITE_USE_MOCK=true pnpm dev` chạy với dữ liệu giả lập.

## Nhóm

| | Thành viên | Phụ trách |
|---|---|---|
| TV1 | Trần Phúc Khánh | Lõi agent, tri thức chẩn đoán |
| TV2 | Phạm Phúc Bình | Bộ công cụ đọc AWS |
| TV3 | Dương Đình Minh (nhóm trưởng) | Hạ tầng, API, kiểm thử, tài liệu |
| TV4 | Lê Minh Đạt | Checklist, giao diện web |
