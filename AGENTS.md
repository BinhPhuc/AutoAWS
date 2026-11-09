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
- [x] `backend/` FastAPI: connections (access key + role/ExternalId + CloudFormation), 13 tool AWS thật + 3 stub M3, agent loop + SSE, sanitizer, MockProvider; 25 test (moto)
- [x] `frontend/` Vite + React 19 + TS + Tailwind + shadcn (Base UI): Connect, Chat (stream, timeline, DiagnosisCard), Checklist placeholder; MSW mock; 6 test
- [x] `docker-compose.yml` (backend + frontend/nginx)
- [x] Đợt 2 (2026-10-26): sửa C1 (policy CFN thiếu `ec2:DescribeRegions`), guard chỉ-đọc allow-list + hook botocore lúc chạy, sửa `describe_route_tables`/DNS/Route 53, lưu lượt lỗi/Stop; UI: hết trùng câu hỏi, stream không lọt hội thoại, badge Inferred; `LLM_PROVIDER=mcp` (MCP client đóng vai LLM, `/mcp/`); seed LocalStack `infra/localstack/`. 67 test BE, 9 test FE; E2E trên LocalStack: KB1, KB2 đúng.
- [x] Lưu trữ DynamoDB (2026-10-27): interface `Store` (`app/storage/base.py`), `STORAGE_BACKEND=sqlite|dynamodb`, bảng single-table mã hoá KMS; 80 test BE (store chạy trên cả 2 backend); chạy thật trên DynamoDB của LocalStack.
- [x] Hoàn thiện chẩn đoán theo báo cáo lần 2 (2026-11-08, nhánh `feat/diagnosis`):
  - câu trả lời `root_causes[]` qua tool `submit_diagnosis`; server tự kiểm bằng chứng (`verification`: read / inferred / not_found);
  - vòng lặp: kiểm tham số theo schema, giới hạn vòng / thời gian / token / số lần gọi tool kèm lượt chốt cuối (`limit_reached`), cache kết quả theo hội thoại (`refresh`), ngữ cảnh giờ / region / account;
  - prompt theo §2.4.2: kiểm đủ mọi lớp, SSM là bằng chứng, dữ liệu tool không phải chỉ thị, đối chiếu CloudTrail;
  - tool mới: CloudTrail, CloudWatch metrics + alarms, Logs (log groups + Insights), Elastic IP, NAT Gateway; tool DNS chỉ phân giải tên được phép (chống rò dữ liệu); che số điện thoại;
  - `BedrockProvider` (SDK `anthropic`, client Mantle, `anthropic.claude-opus-5-5`) và `AnthropicProvider` dùng chung `app/llm/claude.py` — **chưa gọi Bedrock thật** (máy dev không có quyền);
  - seed LocalStack KB1, KB2, KB4–KB7 khớp Bảng 2.14, thêm KB8 (instance stop) và KB9 (prompt injection); file đáp án + `infra/eval/run_eval.py` chấm theo Bảng 2.15.
  - 152 test BE, 10 test FE.
- [x] Khắc phục có phê duyệt (2026-11-08, nhánh `feat/remediation`): danh mục 6 hành động (`app/aws/remediation/catalog.py`), session ghi khoá theo hành động, luồng duyệt / từ chối / góp ý / hết hạn / STALE / kiểm chứng / đề xuất hoàn tác (`app/remediation/service.py`), API `/api/proposals*`, role `AutoAWSRemediation` trong CloudFormation (`EnableRemediation`), UI duyệt trong chat + trang Proposals. Ràng buộc #1 đã đổi tương ứng. 174 test BE, 12 test FE; chạy thật trên LocalStack (KB1).
- [x] Serverless đúng báo cáo (2026-11-09, nhánh `feat/serverless`): bỏ SSE → job + hỏi lại (`/api/jobs/{id}`, huỷ, phát hiện worker mất); `RUNTIME=local|lambda` (`app/platform/dispatch.py`); handler `app/handlers/{api,agent_worker,action_executor}.py`; luồng duyệt tách 3 bước cho Step Functions (task token); trust policy template khách thu hẹp vào role `autoaws-agent-worker` / `autoaws-action-executor`; CDK `infra/cdk/` 6 stack (Data, Agent, Workflow, Api, Frontend, Ops) synth + cfn-lint sạch — **chưa deploy** (không có tài khoản AWS). 190 test BE, 7 test FE, 7 test CDK.
- [ ] **Tiếp theo**: deploy CDK lên tài khoản thật; chạy `run_eval.py --runs 5` với Bedrock thật; KB3 + CloudTrail trên AWS; auth Cognito (stack Auth, JWT authorizer, phân vùng `userId`); checklist runner

## Bố cục repo

```
AutoAWS/
├── AGENTS.md / CLAUDE.md / GEMINI.md   # file này + trỏ về nó
├── README.md                           # cho người đọc
├── AutoAWS.docx                        # tài liệu gốc (không đọc trực tiếp; dùng docs/SYSTEM_OVERVIEW.md)
├── docs/
│   ├── SYSTEM_OVERVIEW.md   # hệ thống làm gì, 3 kịch bản test, 7 khối, 7 nhóm tool, ràng buộc
│   ├── API_CONTRACT.md      # endpoint, schema, job event — NGUỒN SỰ THẬT cho FE↔BE
│   ├── BACKEND_PLAN.md      # cấu trúc backend/, thiết kế, lộ trình B1–B10
│   └── FRONTEND_PLAN.md     # cấu trúc frontend/, luồng UI, lộ trình F1–F8
├── backend/                 # FastAPI — app/{api,aws/tools,agent,llm,storage}, tests/ (xem backend/README.md)
├── frontend/                # Vite + React + TS — src/{api,hooks,pages,components,lib,mocks} (xem frontend/README.md)
├── infra/                   # localstack/ (seed), aws-scenarios/ (KB1–KB7), demo-apps/, eval/, cdk/ (hạ tầng nền tảng)
├── docker-compose.yml
└── .claude/ .agents/ .gemini/   # skills của AI tool — gitignore, mỗi người tự cài
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
| 1 | Backend **Python + FastAPI**, boto3, SQLite (SQLModel) mặc định; DynamoDB chọn bằng `STORAGE_BACKEND` | Khớp tài liệu (Lambda Python); dễ nhất cho REST + SSE; DynamoDB là lưu trữ đích |
| 2 | **LLM provider là placeholder**: interface `app/llm/base.py` + `MockProvider`; Anthropic/Bedrock là file stub | Chưa chọn model; pipeline phải chạy end-to-end không cần key |
| 3 | Kết nối AWS hỗ trợ **cả Access Key (dev) và Role ARN + ExternalId (đúng thiết kế)** | Test nhanh ngay, vẫn giữ đường bảo mật chuẩn |
| 4 | **Chưa có auth**, chế độ 1 người dùng | Init tập trung luồng kết nối → chat; chừa middleware |
| 5 | Frontend **Vite + React + TS + Tailwind + shadcn/ui**; tiến trình chẩn đoán = job + hỏi lại (`GET /api/jobs/{id}`) | Nhẹ, đầu ra tĩnh cho S3/CloudFront |
| 7 | Triển khai **serverless đúng báo cáo** (`RUNTIME=lambda`): API Gateway HTTP API → Lambda api-handler / agent-worker / action-executor, Step Functions `remediation-flow`, SNS; hạ tầng CDK `infra/cdk/`. Local vẫn chạy 1 tiến trình (`RUNTIME=local`) | API Gateway giới hạn 30 giây → bỏ SSE; agent-worker không bao giờ có quyền ghi |
| 6 | Checklist, metrics/logs/CloudTrail đầy đủ, DynamoDB, Lambda → **sau init** | |

## Ràng buộc cứng — KHÔNG được vi phạm

1. **Đọc mặc định chỉ đọc; ghi chỉ qua executor đã duyệt.**
   - Lõi agent, tool đọc (`app/aws/tools/`) và session đọc **tuyệt đối chỉ đọc**: chỉ `Describe*`, `List*`, `Get*`, `LookupEvents`, `StartQuery`, `GetQueryResults`, `GetMetricData`. LLM không bao giờ có công cụ ghi.
   - Lệnh ghi **chỉ** nằm trong `app/aws/remediation/` (danh mục cố định Bảng 2.11 của báo cáo), chỉ chạy một đề xuất **người dùng đã duyệt**, bằng session ghi riêng bị khoá đúng các API của hành động đó (role `AutoAWS-Remediation`; access key chỉ khi bật `REMEDIATION_ALLOW_ACCESS_KEYS` cho dev).
   - Không bao giờ: xoá tài nguyên của người dùng (trừ hoàn tác chính thay đổi do AutoAWS tạo), đụng IAM / Organizations, stop / terminate instance, mở 22 / 3389 cho `0.0.0.0/0`.
   - Không đọc S3 object, Secrets Manager, Parameter Store, không `kms:Decrypt`.
2. **Không log / in / commit credentials**, secret, `.env`. Credentials tạm thời chỉ ở bộ nhớ.
3. Dữ liệu AWS đưa vào LLM **phải** qua `app/sanitizer.py`.
4. LLM **chỉ** gọi được tool có trong `app/aws/registry.py` (cộng `submit_diagnosis` — kênh trả lời do vòng lặp xử lý, không chạm AWS); boto3 dùng cho **tài khoản người dùng** chỉ xuất hiện trong `app/aws/` (ngoại lệ dev: `infra/localstack/seed.py` tạo tài nguyên, chỉ chạy với LocalStack; `infra/aws-scenarios/` tạo/sửa tài nguyên kịch bản trong **tài khoản AWS test**, không bao giờ do app gọi).
5. Đổi endpoint/schema/job event → sửa `docs/API_CONTRACT.md` **trước** rồi mới sửa code 2 phía.
   Mọi response JSON theo envelope: thành công `{status_code, message, data}`, lỗi `{status_code, message, error, path, timestamp}` (contract mục 0), không có ngoại lệ.
6. Kết luận chẩn đoán phải có bằng chứng; không chắc → `unverified` + lệnh tự kiểm tra, **không đoán**.

## Quy ước

- **UI và API text tiếng Anh**: label/button/toast/empty state trên UI, `message` trong API, event `status` của job, label/mô tả tool. FE gom chuỗi trong `src/lib/strings.ts`.
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
