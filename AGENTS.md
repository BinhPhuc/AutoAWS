# AGENTS.md — Hướng dẫn cho AI coding agent (và người mới vào team)

Đây là file **đọc đầu tiên**. Claude Code đọc qua `CLAUDE.md`, Gemini CLI qua `GEMINI.md`, Codex/Cursor/Copilot đọc trực tiếp file này. Giữ file này **ngắn**; chi tiết nằm trong `docs/`.

## Project là gì

**AutoAWS** — trợ lý AI chẩn đoán và khắc phục sự cố trên AWS (bài tập lớn môn Điện toán đám mây, Nhóm 16, UET-VNU).
Người dùng kết nối tài khoản AWS bằng quyền **chỉ đọc**, mô tả sự cố bằng ngôn ngữ tự nhiên; agent (LLM + tool use) gọi **bộ công cụ đọc AWS cố định** (EC2, SG/NACL/route table, Route 53, ELB, CloudWatch, CloudTrail), đối chiếu dữ liệu thật và trả lời: **nguyên nhân → bằng chứng → cách khắc phục → điểm chưa xác nhận**.
Chi tiết: `docs/SYSTEM_OVERVIEW.md` (tóm tắt tài liệu gốc `AutoAWS.docx`).

## Trạng thái hiện tại

> **Hiện tại (2026-11-11): chẩn đoán, khắc phục có phê duyệt, đăng nhập và hai phương án triển khai (CDK serverless, EC2 + Docker) đã có code và test; chạy trọn luồng trên LocalStack với LLM thật. Chưa deploy lên AWS thật, chưa làm checklist.**
> Cập nhật mục này mỗi khi hoàn thành một mốc. Các dòng dưới là nhật ký theo thứ tự thời gian (dòng cũ có thể đã bị dòng sau thay thế).

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
- [x] Hoàn thiện khắc phục có phê duyệt (2026-11-10, nhánh `feat/remediation-complete`): DryRun trước khi ghi cho 4 hành động EC2 (chỉ trên AWS thật — moto/LocalStack bỏ qua DryRun và ghi thật; endpoint không trả `DryRunOperation` thì dừng), khôi phục đề xuất bị ngắt khi backend local khởi động lại, số đề xuất chờ duyệt trên thanh điều hướng. 200 test BE.
- [x] Đăng nhập + phân vùng dữ liệu theo người dùng (2026-11-10, nhánh `feat/auth`): `AUTH_MODE=none|cognito` (`app/auth.py`), `user_id` trên connection / conversation / job / proposal, tài nguyên người khác → 404, lịch sử đề xuất ghi `by`; ExternalId luôn do server sinh; `GET /api/auth/config`, `GET /api/me`; CDK stack `Auth` (Cognito Lite, Hosted UI, client PKCE) + JWT authorizer cho mọi route trừ health / auth config; CloudFront bỏ error response toàn cục (đổi sang CloudFront Function cho SPA); FE: PKCE tự viết (`src/lib/auth.ts`), `AuthGate`, `/auth/callback`, nút Sign out. 223 test BE, 16 test FE, 11 test CDK — **chưa chạy với Cognito thật**.
- [x] Cấu hình demo EC2 + CloudFront + DynamoDB (2026-11-10): `docker-compose.backend.yml` chỉ chạy backend, mặc định dùng DynamoDB và không tự tạo bảng; template `infra/cloudformation/dynamodb.yaml` tạo bảng/index/TTL/KMS, table/region/endpoint điền qua `.env`; sửa thứ tự user/assistant khi timestamp trùng, bổ sung `tzdata` cho Windows/image tối giản. 209 test BE, ruff + cfn-lint sạch. **Chưa deploy AWS thật.**
- [x] Hợp nhất DynamoDB với auth của `main` (2026-11-10): giữ triển khai Cognito/phân vùng người dùng từ `feat/auth`; giữ template DynamoDB, Compose EC2, mặc định DynamoDB và kiểm tra bảng lúc startup từ `feat/cognito-auth-user-isolation`; thêm 3 test auth trên DynamoDB. 235 test BE, 16 test FE, 11 test CDK; lint/build đạt. **Chưa deploy AWS thật.**
- [x] Cognito độc lập cho EC2 + CloudFront (2026-11-10): template `infra/cloudformation/cognito.yaml` (Lite, Hosted UI classic, public client cho PKCE, callback/logout khớp FE), Outputs cấu hình backend và hướng dẫn `infra/cloudformation/COGNITO.md`; cfn-lint sạch. **Chưa deploy AWS thật.**
- [x] Cognito trên localhost (2026-11-10): template mặc định `FrontendUrl=http://localhost:5173`, cho phép HTTP chỉ với hostname localhost, tránh callback/logout trùng khi bật `AllowLocalhost`; bổ sung hướng dẫn chạy backend/frontend local. cfn-lint và kiểm tra các tổ hợp URL đạt; **chưa thử đăng nhập Cognito thật**.
- [x] Sửa credentials khi chạy uvicorn local (2026-11-10): nạp `.env` vào môi trường trước khi tạo Settings để SDK AWS nhận access key/session token; giữ ưu tiên biến môi trường có sẵn. Đã khởi động backend với DynamoDB thật và health trả 200; chưa kiểm tra đăng nhập Cognito/Bedrock thật.
- [x] Đồng bộ `/connect` theo nhánh `dev` (2026-11-10): form sinh/hiển thị External ID trước khi tạo role, hướng dẫn IAM thủ công và preview/tải CloudFormation, backend giữ đúng ID đã dùng trong trust policy thay vì sinh lại; verify ngay khi lưu, thử lại trên cùng connection. Giữ bố cục bảng/hộp thoại; form chỉ có IAM thủ công hoặc CloudFormation (mặc định, Recommended), bỏ Access Key khỏi form. Policy dùng đúng principal nền tảng và endpoint vẫn yêu cầu auth. 247 test BE, 20 test FE; lint/build đạt; kiểm tra Chrome desktop/mobile bằng MSW và STS qua moto, **chưa verify với AWS thật**. Luồng External ID này thay thế cách luôn sinh tại server ở mốc auth trước đó.
- [x] Model local qua Ollama (2026-11-10): chuyển OpenAI-compatible provider từ `dev`, `LLM_PROVIDER=openai`, cấu hình URL/model/key/timeout/token; dùng lại job, sanitizer, registry và `submit_diagnosis`, đếm token theo giới hạn agent. 289 test BE, ruff sạch; smoke test Ollama thật `qwen2.5:latest` chọn `describe_instances`, nhận dữ liệu mô phỏng và gọi `submit_diagnosis` đúng schema. **Chưa đánh giá chẩn đoán AWS thật bằng Qwen.**
- [x] Trả lời gọn theo `dev` (2026-11-11): prompt chỉ điều tra trong phạm vi câu hỏi, dừng khi có nguyên nhân chặn đủ để trả lời; tóm tắt 1–2 câu, lời chào/cảm ơn hoặc hỏi lại không gọi AWS. Giữ job, `submit_diagnosis`, kiểm chứng bằng chứng và phê duyệt khắc phục. Thêm `infra/ollama/Modelfile` cho Qwen context 16.384, temperature 0.2; context 4.096 trên máy dev không đủ giữ prompt và bộ tool. 289 test BE và ruff đạt; smoke test Qwen thật qua agent loop: “hi”, “cảm ơn”, “giúp tôi với” đều trả lời ngắn bằng tiếng Việt, không gọi AWS. Chưa đánh giá lại chẩn đoán AWS thật.
- [x] Gộp phần còn nằm ngoài `main` + rà soát (2026-11-11, nhánh `chore/sync-final-readme`): CDK deploy **một lần** (HTTP API rỗng tạo ở stack Frontend để cắt vòng CloudFront ↔ Cognito ↔ authorizer; `frontendUrl` chỉ còn dùng cho tên miền riêng); `LLM_PROVIDER=anthropic` + `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` = gateway định dạng Anthropic ở chế độ tương thích (không thinking / effort / beta), `ANTHROPIC_GATEWAY_CACHE` gắn `cache_control` cho phần lặp lại — đã chạy thật KB1, KB2 trên LocalStack qua một gateway (model Gemini); sửa `infra/eval/run_eval.py` còn đọc SSE (hỏng từ khi đổi sang job); README viết lại; hướng dẫn LocalStack tạo kết nối Access Key qua API (form chỉ còn IAM role). 293 test BE, 20 test FE, 13 test CDK.
- [x] External ID do server cấp (2026-11-11, nhánh `final`): `GET /api/connections/setup` trả `external_id` = `autoaws-<nonce>-<HMAC(EXTERNAL_ID_SECRET, user_id:nonce)>` (`app/external_id.py`, không lưu trạng thái); `POST /api/connections` và `cloudformation-preview` chỉ nhận mã server cấp cho đúng người gọi (`400 EXTERNAL_ID_INVALID`), mã đã có kết nối dùng → `409 EXTERNAL_ID_IN_USE`; giữ luồng của Bình (mã hiện trước khi tạo role), ô External ID chỉ đọc, Regenerate xin mã mới; bắt buộc `EXTERNAL_ID_SECRET` khi `AUTH_MODE=cognito` / `RUNTIME=lambda`, CDK sinh khoá trong Secrets Manager. 305 test BE, 20 test FE, 14 test CDK.
- [x] Sửa kết nối sau khi tạo (2026-11-12, nhánh `feat/edit-connections-proposals`): `PATCH /api/connections/{id}` nhận `name` / `region` / `role_arn` / `remediation_role_arn` (không đổi `type` / `external_id`); đổi region hoặc role → `pending`, xoá session cache, FE tự verify lại; cache session khoá theo (role, External ID, region); `DEFAULT_REGION` → `default_region` trong `GET /api/connections/setup` cho form; nút Edit + hộp thoại trên bảng kết nối. Backend `POST /api/proposals/{id}/revise` (đề xuất mới có `parent_id`, đề xuất cũ đang chờ → SUPERSEDED). 321 test BE, 25 test FE, 15 test CDK.
- [x] Chạy thật KB1, KB3–KB7 trên tài khoản AWS test (2026-11-13, LLM qua gateway): chẩn đoán đúng cả 6 kịch bản; khắc phục KB1 trọn luồng (sửa đề xuất → duyệt → DryRun → ghi bằng `AutoAWSRemediation` → kiểm chứng). Sửa: session role chỉ dùng lại nếu còn sống hết một job (trước đây hết hạn giữa job), thử lại khi gateway báo lỗi giữa stream, `scenario.py down kb1` không còn kẹt xoá stack, `run_eval.py --connection`. Chưa chạy KB2 (cần tên miền).
- [x] UI sửa đề xuất (2026-11-13, nhánh `feat/proposal-edit-ui`): nút Edit trên thẻ đề xuất ở các trạng thái PENDING_APPROVAL / REJECTED / EXPIRED / STALE / SUPERSEDED (chưa có bản sửa); form sinh từ `input_schema` của hành động (string + pattern / enum / maxLength, integer + min / max, trường tuỳ chọn để trống thì bỏ), lỗi pre-check của server hiện ngay trong hộp thoại; bản sửa hiện lồng dưới đề xuất gốc. 330 test BE (thêm `test_revise_proposals.py`: thay đề xuất chờ, pre-check / schema hỏng giữ nguyên bản gốc, sửa sau REJECTED / STALE, không sửa được bản đã áp dụng / rollback, chạy qua agent-worker trên Lambda, người khác → 404), 36 test FE.
- [ ] **Tiếp theo** (xếp theo ưu tiên): deploy thật một phương án (CDK hoặc EC2) rồi thử Cognito + Bedrock; `run_eval.py --runs 5` với LLM thật; KB3 + CloudTrail trên AWS; CI (GitHub Actions: pytest, ruff, vitest, build, test CDK); mặc định an toàn hơn (`CORS_ORIGINS`, `AUTH_MODE` trong Compose EC2); checklist runner

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
├── infra/                   # cloudformation/ (DynamoDB EC2), localstack/, aws-scenarios/, demo-apps/, eval/, cdk/
├── docker-compose.yml
├── docker-compose.backend.yml  # backend EC2 + DynamoDB; frontend build riêng lên CloudFront
└── .claude/ .agents/ .gemini/   # skills của AI tool — gitignore, mỗi người tự cài
```

## Chạy project

```bash
# Backend (port 8000)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cp .env.example .env     # điền DYNAMODB_TABLE/REGION hoặc STORAGE_BACKEND=sqlite cho local
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
| 1 | Backend **Python + FastAPI**, boto3, **DynamoDB mặc định** (bảng tạo bằng IaC); SQLite chỉ bật tường minh cho local/test | Khớp lưu trữ đích; EC2 không cần database volume |
| 2 | **LLM sau một interface** (`app/llm/base.py`), chọn bằng `LLM_PROVIDER`: `bedrock` (đích), `anthropic` (kể cả gateway), `openai` (Ollama / tương thích OpenAI), `mcp`, `mock` (mặc định) | Pipeline chạy end-to-end không cần key; đổi model không đụng vòng lặp agent |
| 3 | Kết nối AWS: **Role ARN + ExternalId** (đúng thiết kế, kiểu duy nhất trên form); **Access Key** chỉ tạo qua API cho dev / LocalStack | Giữ đường bảo mật chuẩn; vẫn test nhanh được với LocalStack |
| 4 | **Auth: `AUTH_MODE=none`** (dev, 1 người dùng `local`) **hoặc `cognito`** (bản triển khai: Cognito + JWT authorizer, dữ liệu tách theo `user_id`) | Dev/test không cần Cognito; bản AWS luôn bật đăng nhập |
| 5 | Frontend **Vite + React + TS + Tailwind + shadcn/ui**; tiến trình chẩn đoán = job + hỏi lại (`GET /api/jobs/{id}`) | Nhẹ, đầu ra tĩnh cho S3/CloudFront |
| 7 | Triển khai **serverless đúng báo cáo** (`RUNTIME=lambda`): API Gateway HTTP API → Lambda api-handler / agent-worker / action-executor, Step Functions `remediation-flow`, SNS; hạ tầng CDK `infra/cdk/`. Local vẫn chạy 1 tiến trình (`RUNTIME=local`) | API Gateway giới hạn 30 giây → bỏ SSE; agent-worker không bao giờ có quyền ghi |
| 6 | Checklist → **chưa làm** (metrics / logs / CloudTrail, DynamoDB, Lambda đã xong) | |

## Ràng buộc cứng — KHÔNG được vi phạm

1. **Đọc mặc định chỉ đọc; ghi chỉ qua executor đã duyệt.**
   - Lõi agent, tool đọc (`app/aws/tools/`) và session đọc **tuyệt đối chỉ đọc**: chỉ `Describe*`, `List*`, `Get*`, `LookupEvents`, `StartQuery`, `GetQueryResults`, `GetMetricData`. LLM không bao giờ có công cụ ghi.
   - Lệnh ghi **chỉ** nằm trong `app/aws/remediation/` (danh mục cố định Bảng 2.11 của báo cáo), chỉ chạy một đề xuất **người dùng đã duyệt**, bằng session ghi riêng bị khoá đúng các API của hành động đó (role `AutoAWS-Remediation`; access key chỉ khi bật `REMEDIATION_ALLOW_ACCESS_KEYS` cho dev).
   - Không bao giờ: xoá tài nguyên của người dùng (trừ hoàn tác chính thay đổi do AutoAWS tạo), đụng IAM / Organizations, stop / terminate instance, mở 22 / 3389 cho `0.0.0.0/0`.
   - Không đọc S3 object, Secrets Manager, Parameter Store, không `kms:Decrypt` (trên tài khoản người dùng; khoá `EXTERNAL_ID_SECRET` của chính nền tảng được CloudFormation đưa vào Lambda, app không gọi Secrets Manager).
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
- TypeScript: strict, oxlint + prettier; kiểu API chỉ khai báo ở `frontend/src/api/types.ts`.
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
