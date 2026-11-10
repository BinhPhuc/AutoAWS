# AutoAWS — Kế hoạch Frontend (bản init)

> Trạng thái: **đã duyệt (2026-10-16)**. Thực hiện theo lộ trình mục 6; tick checkbox khi xong.
> Đọc trước: `docs/SYSTEM_OVERVIEW.md` (hệ thống làm gì), `docs/API_CONTRACT.md` (endpoint, schema, SSE event — nguồn sự thật).

## 1. Mục tiêu bản init

Giao diện web **ReactJS** cho người dùng thao tác thật:
1. **Kết nối tài khoản AWS** (Access Key hoặc Role ARN + ExternalId) → bấm Verify → thấy badge **"Connected"** (mốc M1).
2. **Chat chẩn đoán**: gõ mô tả sự cố → thấy từng bước agent đang đọc gì (timeline tool call) → nhận **thẻ kết quả có cấu trúc** (Root cause / Evidence / How to fix / Not verified) → hỏi tiếp cùng hội thoại.

> **Ngôn ngữ UI: tiếng Anh** cho mọi text do FE sinh ra (label, button, toast, empty state, placeholder, tiêu đề mục trong DiagnosisCard). **Nội dung câu trả lời của agent** (`DiagnosisAnswer`) đến từ backend và là **tiếng Việt** — FE chỉ hiển thị. Không i18n ở bản init; gom text vào `src/lib/strings.ts`. Tài liệu/comment nội bộ tiếng Việt hoặc Anh đều được.
3. Chạy được ngay với backend ở chế độ `LLM_PROVIDER=mock` và cả khi **chưa có backend** (mock data theo contract) để FE/BE làm song song.

Ngoài phạm vi init: đăng ký/đăng nhập, màn checklist (chỉ placeholder), deploy S3/CloudFront.

## 2. Stack & lý do

| Thành phần | Chọn | Lý do |
|---|---|---|
| Build | **Vite** + React 18 + TypeScript (strict) | Nhanh, cấu hình tối thiểu; đầu ra tĩnh → S3/CloudFront sau |
| UI | **Tailwind CSS** + **shadcn/ui** | Component sẵn (Tabs, Card, Badge, Dialog, Collapsible, Toast), dễ chỉnh; repo đã có skill `ui-ux-pro-max` / `ui-styling` hỗ trợ agent |
| Routing | react-router v6 | 3 trang |
| Server state | TanStack Query | Cache danh sách connection/conversation, invalidate sau mutation |
| Streaming | `fetch` + `ReadableStream` tự parse SSE (POST nên không dùng `EventSource`) | ~40 dòng, không thêm lib |
| Icons | lucide-react (đi kèm shadcn) | |
| Lint/format | eslint + prettier | |
| Test | vitest + React Testing Library (ít, cho parser SSE và DiagnosisCard) | |
| Package manager | **pnpm** (máy dev có pnpm 11) | |
| Mock khi chưa có BE | MSW (Mock Service Worker) với handlers theo `API_CONTRACT.md` | Bật bằng `VITE_USE_MOCK=true` |

## 3. Cấu trúc thư mục `frontend/`

```
frontend/
├── index.html, vite.config.ts (proxy /api → http://localhost:8000), tsconfig.json, tailwind.config.ts
├── package.json, .env.example (VITE_API_URL=, VITE_USE_MOCK=false)
├── components.json           # shadcn
├── Dockerfile                # build → nginx serve dist, proxy /api
└── src/
    ├── main.tsx              # QueryClientProvider, RouterProvider, (MSW nếu VITE_USE_MOCK)
    ├── App.tsx               # layout: sidebar trái (nav + danh sách hội thoại) + nội dung
    ├── routes.tsx            # "/" → redirect; "/connect"; "/chat/:conversationId?"; "/checklist"
    ├── api/
    │   ├── client.ts         # apiFetch<T>(path, init): base URL, JSON; bóc envelope → trả `data` (T) + `message`; ném ApiError{status_code,message,error,path,timestamp}
    │   ├── sse.ts            # streamSSE(path, body, onEvent): parse "event:/data:" từ ReadableStream
    │   ├── types.ts          # Connection, Conversation, Message, ToolCall, DiagnosisAnswer, AgentEvent — mirror contract
    │   ├── connections.ts    # list/create/remove/verify/getCloudFormation
    │   ├── conversations.ts  # list/create/get/remove
    │   └── tools.ts          # listTools
    ├── mocks/                # MSW: handlers.ts (CRUD in-memory), sseFixtures.ts (chuỗi event KB1/KB2/KB3), browser.ts
    ├── hooks/
    │   ├── useConnections.ts     # useQuery + mutations (create/remove/verify)
    │   ├── useConversations.ts
    │   ├── useSendMessage.ts     # gọi streamSSE; state: status text, liveToolCalls[], answer; khi done → invalidate conversation
    │   └── useTools.ts
    ├── pages/
    │   ├── ConnectPage.tsx       # danh sách kết nối + nút "Thêm kết nối" (Dialog chứa ConnectionForm)
    │   ├── ChatPage.tsx          # chọn connection (Select) → tạo/đổi hội thoại; MessageList + Composer
    │   └── ChecklistPage.tsx     # placeholder "Coming soon" + mô tả tính năng
    ├── components/
    │   ├── layout/   AppShell, Sidebar (nav + ConversationList), ConnectionBadge (tên + trạng thái hiện tại)
    │   ├── connections/
    │   │   ├── ConnectionForm.tsx       # Tabs: "Access Key" | "IAM Role (khuyến nghị)"; validation; submit → create → verify
    │   │   ├── ConnectionCard.tsx       # tên, type, region, account_id, status badge, nút Verify / Xoá
    │   │   ├── RegionSelect.tsx         # danh sách region phổ biến (ap-southeast-1 mặc định)
    │   │   └── CloudFormationSnippet.tsx# hiện ExternalId + template YAML (lấy từ API) + nút Copy + hướng dẫn 3 bước
    │   ├── chat/
    │   │   ├── MessageList.tsx          # cuộn; user bubble / assistant block
    │   │   ├── UserMessage.tsx
    │   │   ├── AssistantMessage.tsx     # = ToolCallTimeline + DiagnosisCard (+ content nếu không có answer)
    │   │   ├── ToolCallTimeline.tsx     # Collapsible: mỗi tool: icon theo group, label (từ GET /api/tools), input, output_summary, duration, trạng thái
    │   │   ├── DiagnosisCard.tsx        # 4 mục; mỗi evidence có badge "Verified from AWS" (verified) ; unverified có badge "Check manually" + code lệnh
    │   │   ├── StreamingStatus.tsx      # dòng "Reading security groups…" (text từ event status) + spinner khi đang stream
    │   │   ├── Composer.tsx             # textarea, Enter gửi / Shift+Enter xuống dòng, disable khi đang stream, gợi ý 3 câu hỏi mẫu (KB1–3)
    │   │   └── EmptyChat.tsx            # chưa có hội thoại: hướng dẫn + 3 nút câu hỏi mẫu
    │   └── ui/                          # shadcn generated
    ├── lib/
    │   ├── toolIcons.ts      # map group → icon (label lấy từ API /api/tools, không hard-code ở FE)
    │   ├── strings.ts        # mọi text UI (tiếng Anh) gom một chỗ
    │   └── utils.ts          # cn(), formatTime()
    └── styles/globals.css
```

## 4. Luồng màn hình

```
Mở app
 └─ chưa có connection "connected"? ──► /connect
      ConnectPage: [Thêm kết nối] → Dialog ConnectionForm
        Tab "Access Key": name, region, access_key_id, secret_access_key → Lưu & kiểm tra
        Tab "IAM Role":   name, region, role_arn, external_id (tự sinh, có thể sửa)
                          → sau khi tạo: CloudFormationSnippet (copy template, hướng dẫn tạo stack) → [Kiểm tra kết nối]
      Kết quả verify → badge "Connected" (xanh) / "Failed" (đỏ, hiện last_error)
 └─ có connection ──► /chat
      Sidebar: chọn connection, danh sách hội thoại, [+ Hội thoại mới]
      ChatPage: EmptyChat hoặc MessageList
        gửi câu hỏi → useSendMessage:
          status      → StreamingStatus cập nhật dòng chữ
          tool_call   → thêm mục vào ToolCallTimeline (đang chạy)
          tool_result → cập nhật mục (ok/error, summary, ms)
          answer      → render DiagnosisCard
          error       → toast + ghi vào khung chat
          done        → invalidate GET /conversations/{id}, mở lại Composer
```

## 5. Chi tiết component quan trọng

### `api/client.ts`
```ts
type Envelope<T> = { status_code: number; message: string; data: T };
export class ApiError extends Error { status_code; error; path; timestamp }   // đúng JSON lỗi của contract mục 0
export async function apiFetch<T>(path, init?): Promise<{ data: T; message: string }>
// !res.ok → parse JSON lỗi → throw ApiError; res.ok → return { data: body.data, message: body.message }
```
Hooks dùng `data`; `message` dùng cho toast sau mutation (tạo/xoá/verify). Toast lỗi hiện `ApiError.message`; rẽ nhánh logic theo `ApiError.error` (ví dụ `CONNECTION_NOT_VERIFIED` → điều hướng về `/connect`).

### `api/sse.ts`
```ts
export async function streamSSE(path: string, body: unknown, onEvent: (e: AgentEvent) => void, signal?: AbortSignal)
// fetch POST, đọc reader; buffer theo "\n\n"; mỗi block: event: X / data: {...} → onEvent({type: X, data})
// !res.ok (lỗi trước khi stream) → ném ApiError như client.ts; lỗi trong stream đến qua event "error"
```

### `DiagnosisCard`
- Header: `summary` + badge `confidence` ("High / Medium / Low confidence").
- Mục **Root cause** (`cause`).
- Mục **Evidence**: list; mỗi item có `source` (tên tool → label từ `/api/tools`) và badge **"Verified from AWS"** nếu `verified`.
- Mục **How to fix**: ordered list `fix_steps`.
- Mục **Not verified**: list `unverified` với badge **"Check manually"** + `how_to_check` dạng `<code>` có nút copy. Ẩn mục nếu rỗng.

### `ToolCallTimeline`
- Mặc định thu gọn thành 1 dòng: "Read 4 data sources · 1.2s"; mở ra thấy từng tool.
- Khi đang stream: mục cuối hiện spinner.

### `ConnectionForm`
- Validation: ARN regex `^arn:aws:iam::\d{12}:role/.+`, access key `^AKIA[0-9A-Z]{16}$`, region bắt buộc.
- Không bao giờ hiển thị lại secret sau khi lưu (contract chỉ trả `access_key_id_masked`).
- Tab IAM Role được đánh dấu **"Recommended"**; tab Access Key có ghi chú "For learning/dev environments only".

## 6. Lộ trình thực hiện (tick khi xong)

- [x] **F1 Scaffold**: `pnpm create vite` (react-ts), Tailwind, shadcn init (+ button, card, badge, tabs, dialog, input, textarea, select, collapsible, toast, scroll-area), react-router, TanStack Query, eslint/prettier. Layout `AppShell` + 3 route rỗng. Proxy `/api`.
- [x] **F2 API layer**: `types.ts` theo contract, `client.ts`, `sse.ts`, 3 module API, hooks. MSW handlers + SSE fixtures (KB1–KB3) để chạy `VITE_USE_MOCK=true`.
- [x] **F3 ConnectPage**: ConnectionList/Card, ConnectionForm 2 tab, verify flow, CloudFormationSnippet.
- [x] **F4 ChatPage**: Sidebar hội thoại, chọn connection, Composer, MessageList, `useSendMessage` stream (hiện text thô trước).
- [x] **F5 ToolCallTimeline + DiagnosisCard + StreamingStatus + EmptyChat** (icon theo group trong `toolIcons.ts`, label từ API).
- [x] **F6 Polish**: loading/empty/error state, toast lỗi, responsive (sidebar thành drawer < 768px), dark mode (shadcn), a11y cơ bản.
- [x] **F7 Dockerfile + nginx** (serve dist, proxy `/api` → backend) + mục trong `docker compose` ở root.
- [x] **F8 Cập nhật `AGENTS.md`** (trạng thái, lệnh chạy FE thật).

Hoàn thành 2026-10-16. Đã kiểm tra tích hợp thật với backend (không MSW) trên browser: connect → verify → chat → stream → DiagnosisCard, console không lỗi.

Ước tính: F1–F2 ≈ 1 ngày, F3 ≈ 1 ngày, F4–F5 ≈ 1.5 ngày, F6–F8 ≈ 0.5 ngày.

## 7. Sau init (không làm bây giờ)
- ~~Đăng nhập Cognito (Hosted UI, PKCE) → gắn `Authorization` vào `client.ts`~~ — **đã làm (2026-11-10)**: `src/lib/auth.ts` (PKCE, refresh, sign out), `AuthGate` + `/auth/callback`, `UserMenu` trên HeaderBar; cấu hình lấy từ `GET /api/auth/config`.
- Màn Checklist: chọn/tải checklist, bảng kết quả từng mục cập nhật dần, báo cáo tổng hợp.
- Hiển thị chỉ số/log (M3): mini chart cho metric, bảng log entries trong ToolCallTimeline.
- Deploy S3 + CloudFront qua CDK.

## 8. Quy tắc bắt buộc (cho mọi người/agent sửa frontend)
1. Mọi kiểu dữ liệu API khai báo **một nơi** `src/api/types.ts`, bám `API_CONTRACT.md`; không tự tạo field mới ở component.
2. Không gọi `fetch` ngoài `src/api/`; component dùng hooks.
3. Mọi text hiển thị cho người dùng **tiếng Anh**, gom trong `src/lib/strings.ts`; không hard-code chuỗi trong component.
4. Không lưu secret vào localStorage; không log body request chứa secret.
5. Component mới dùng shadcn/ui trước khi tự viết; kiểm tra `ui-ux-pro-max` skill khi cần quyết định UI.
