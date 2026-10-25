# AGENTS.md — Hướng dẫn cho AI coding agent (và người mới vào team)

Đây là file **đọc đầu tiên**. Claude Code đọc qua `CLAUDE.md`, Gemini CLI qua `GEMINI.md`, Codex/Cursor/Copilot đọc trực tiếp file này. Giữ file này **ngắn**; chi tiết nằm trong `docs/`.

## Project là gì

**AutoAWS** — trợ lý AI chẩn đoán và khắc phục sự cố trên AWS (đồ án môn Điện toán đám mây, Nhóm 16, UET-VNU).
Người dùng kết nối tài khoản AWS bằng quyền **chỉ đọc**, mô tả sự cố bằng ngôn ngữ tự nhiên; agent (LLM + tool use) gọi **bộ công cụ đọc AWS cố định** (EC2, SG/NACL/route table, Route 53, ELB, CloudWatch, CloudTrail), đối chiếu dữ liệu thật và trả lời: **nguyên nhân → bằng chứng → cách khắc phục → điểm chưa xác nhận**.
Chi tiết: `docs/SYSTEM_OVERVIEW.md` (tóm tắt tài liệu gốc `AutoAWS.docx`).

## Trạng thái hiện tại

> **Giai đoạn: INIT hoàn thành (2026-10-16) — chạy được end-to-end local với `LLM_PROVIDER=mock`.**
> Cập nhật mục này mỗi khi hoàn thành một mốc.

- [x] Kế hoạch backend/frontend (`docs/*_PLAN.md`) — đã duyệt, mọi task B1–B10, F1–F8 đã tick
- [x] Hợp đồng API `docs/API_CONTRACT.md`
- [x] `backend/` FastAPI: connections (access key + role/ExternalId + CloudFormation), 13 tool AWS thật + 3 stub M3, agent loop + SSE, sanitizer, mock/Bedrock/OpenAI-compatible; 91 test (2026-10-26, AWS giả lập bằng moto)
- [x] `frontend/` Vite + React 19 + TS + Tailwind + shadcn (Base UI): Connect, Chat (stream, timeline, DiagnosisCard), Checklist placeholder; MSW mock; 6 test
- [x] Connect: giao diện chỉ dùng IAM Role với hai cách IAM thủ công/CloudFormation trước khi lưu connection; popup hướng dẫn tạo `AutoAWSReadOnly` từ đầu, trust/permissions policy điền sẵn account AutoAWS và lấy ARN; CLI tùy chọn; popup đóng khi bấm ngoài, Region neo bên dưới (2026-10-25).
- [x] `docker-compose.yml` (backend + frontend/nginx); AssumeRole/Bedrock đọc credentials trực tiếp từ `backend/.env`, không cần AWS profile trên host (2026-10-25).
- [x] Bedrock Converse + tool use, demo API/UI với tool giả, tối đa 10 lượt; đã cấu hình Nova Micro và gọi Bedrock thật, đang bị AWS từ chối `Operation not allowed` ở cấp tài khoản (2026-10-26); backend đã báo lỗi cụ thể và log Request ID.
- [x] Ưu tiên OpenAI-compatible (`LLM_PROVIDER=openai`): Chat Completions/tool calling async, cấu hình endpoint/model/key trong `.env`, hỗ trợ local Ollama không cần key; kiểm thử protocol/SSE/sanitizer/giới hạn 10 vòng (2026-10-26). Chưa smoke test model Ollama thật vì máy chưa có server/model.
- [ ] **Tiếp theo**: smoke test Ollama thật; `AnthropicProvider` thật (`backend/app/llm/anthropic.py`); tool M3 (`metrics.py`, `logs.py`, `cloudtrail.py`); checklist runner; auth Cognito

## Bố cục repo

```
AutoAWS/
├── AGENTS.md / CLAUDE.md / GEMINI.md   # file này + trỏ về nó
├── README.md                           # cho người đọc
├── AutoAWS.docx                        # tài liệu gốc (không đọc trực tiếp; dùng docs/SYSTEM_OVERVIEW.md)
├── docs/
│   ├── SYSTEM_OVERVIEW.md   # hệ thống làm gì, 3 kịch bản test, 7 khối, 7 nhóm tool, ràng buộc
│   ├── API_CONTRACT.md      # endpoint, schema, SSE event — NGUỒN SỰ THẬT cho FE↔BE
│   ├── BACKEND_PLAN.md      # cấu trúc backend/, thiết kế, lộ trình B1–B10
│   └── FRONTEND_PLAN.md     # cấu trúc frontend/, luồng UI, lộ trình F1–F8
├── backend/                 # FastAPI — app/{api,aws/tools,agent,llm,storage}, tests/ (xem backend/README.md)
├── frontend/                # Vite + React + TS — src/{api,hooks,pages,components,lib,mocks} (xem frontend/README.md)
├── docker-compose.yml
└── .claude/ .agents/ .gemini/   # skills thiết kế UI dùng chung (ui-ux-pro-max, ui-styling, ...)
```

## Chạy project

```bash
# Backend (port 8000)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cp .env.example .env     # LLM_PROVIDER=mock mặc định
uvicorn app.main:app --reload                       # docs: http://localhost:8000/docs

# Frontend (port 5173, proxy /api → 8000)
cd frontend && pnpm install && cp .env.example .env && pnpm dev
VITE_USE_MOCK=true pnpm dev                         # không cần backend (MSW)

# Test / lint
cd backend  && pytest && ruff check app tests
cd frontend && pnpm test && pnpm lint && pnpm build

# Docker (cả 2)
docker compose up --build                            # FE http://localhost:5173, BE :8000
```
Máy dev tham chiếu: Node 24 + pnpm 11, Python 3.14, Docker. Không có AWS CLI / uv.
Chưa có tài khoản AWS? Test backend dùng **moto**; để chạy demo thật cần Access Key (dev) hoặc Role ARN + tài khoản nền tảng (`PLATFORM_AWS_*` trong `backend/.env`).

## Quyết định đã chốt (ADR mini)

| # | Quyết định | Lý do |
|---|---|---|
| 1 | Backend **Python + FastAPI**, boto3, SQLite (SQLModel) | Khớp tài liệu (Lambda Python); dễ nhất cho REST + SSE |
| 2 | **Ưu tiên OpenAI-compatible** (Ollama tự host) qua `LLM_PROVIDER=openai`; Bedrock Converse là lựa chọn khác, mock mặc định cho test; Anthropic còn stub | Đổi endpoint/model qua `.env`, agent/tool AWS dùng chung; chạy pipeline được khi chưa có model server |
| 3 | Kết nối AWS hỗ trợ **cả Access Key (dev) và Role ARN + ExternalId (đúng thiết kế)** | Test nhanh ngay, vẫn giữ đường bảo mật chuẩn |
| 4 | **Chưa có auth**, chế độ 1 người dùng | Init tập trung luồng kết nối → chat; chừa middleware |
| 5 | Frontend **Vite + React + TS + Tailwind + shadcn/ui**, SSE qua fetch stream | Nhẹ, đầu ra tĩnh cho S3/CloudFront sau |
| 6 | Checklist, metrics/logs/CloudTrail đầy đủ, DynamoDB, Lambda → **sau init** | |

## Ràng buộc cứng — KHÔNG được vi phạm

1. **Chỉ đọc AWS.** Không bao giờ thêm action tạo/sửa/xoá (chỉ `Describe*`, `List*`, `Get*`, `LookupEvents`, `StartQuery`, `GetQueryResults`, `GetMetricData`). Không đọc S3 object, Secrets Manager, Parameter Store, không `kms:Decrypt`.
2. **Không log / in / commit credentials**, secret, `.env`. Credentials tạm thời chỉ ở bộ nhớ.
3. Dữ liệu AWS đưa vào LLM **phải** qua `app/sanitizer.py`.
4. LLM **chỉ** gọi được tool có trong `app/aws/registry.py`; boto3 chỉ xuất hiện trong `app/aws/`.
5. Đổi endpoint/schema/SSE event → sửa `docs/API_CONTRACT.md` **trước** rồi mới sửa code 2 phía.
   Mọi response JSON theo envelope: thành công `{status_code, message, data}`, lỗi `{status_code, message, error, path, timestamp}` (contract mục 0). Chỉ SSE là ngoại lệ.
6. Kết luận chẩn đoán phải có bằng chứng; không chắc → `unverified` + lệnh tự kiểm tra, **không đoán**.

## Quy ước

- **UI và API text tiếng Anh**: label/button/toast/empty state trên UI, `message` trong API, status SSE, label/mô tả tool. FE gom chuỗi trong `src/lib/strings.ts`.
- **Câu trả lời của agent tiếng Việt**: `DiagnosisAnswer` và `content` của assistant (system prompt ép đầu ra tiếng Việt; tên tài nguyên/lệnh/mã lỗi AWS giữ nguyên).
- Tài liệu trong `docs/` và commit body: tiếng Việt. Code (tên biến/hàm/file, comment), commit subject: tiếng Anh, dạng conventional (`feat(backend): add describe_route_tables tool`).
- Python: ruff (lint + format), type hints đầy đủ, pytest + moto cho mọi tool AWS.
- TypeScript: strict, eslint + prettier; kiểu API chỉ khai báo ở `frontend/src/api/types.ts`.
- Tool AWS mới = 1 hàm `@tool(...)` trong `backend/app/aws/tools/` + test + 1 dòng trong bảng cuối `API_CONTRACT.md`.
- Hoàn thành task trong plan → tick checkbox trong `docs/*_PLAN.md` và cập nhật mục "Trạng thái" ở trên.

## Làm task nào thì đọc gì

| Task | Đọc |
|---|---|
| Hiểu nghiệp vụ / viết prompt chẩn đoán | `docs/SYSTEM_OVERVIEW.md` §4 (3 kịch bản), §5, §6 |
| Thêm/sửa tool AWS (TV2) | `docs/BACKEND_PLAN.md` §4.2, `API_CONTRACT.md` bảng tool |
| Lõi agent / LLM provider (TV1) | `docs/BACKEND_PLAN.md` §4.3–4.4, `backend/app/llm/base.py` |
| Giao diện chat / kết nối (TV4) | `docs/FRONTEND_PLAN.md`, `API_CONTRACT.md` §2–3 |
| API, hạ tầng, CI (TV3) | `docs/BACKEND_PLAN.md` §3, §6; `docs/SYSTEM_OVERVIEW.md` §7 |
| Checklist | Chưa làm — xem `SYSTEM_OVERVIEW.md` §3 giai đoạn C, `BACKEND_PLAN.md` §6 |

## Thành viên

TV1 Trần Phúc Khánh (lõi agent, prompt) · TV2 Phạm Phúc Bình (tool đọc AWS) · TV3 Dương Đình Minh — nhóm trưởng (hạ tầng, API, kiểm thử) · TV4 Lê Minh Đạt (checklist, giao diện web).
