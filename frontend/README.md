# AutoAWS — Frontend

Vite + React + TypeScript + Tailwind + shadcn/ui. Chi tiết thiết kế: `../docs/FRONTEND_PLAN.md`, hợp đồng API: `../docs/API_CONTRACT.md`.

## Chạy

```bash
pnpm install
cp .env.example .env

# Chạy với backend thật (FastAPI ở http://localhost:8000, Vite proxy /api)
pnpm dev

# Chạy KHÔNG cần backend (MSW mock theo API_CONTRACT, có sẵn 3 kịch bản KB1–KB3)
VITE_USE_MOCK=true pnpm dev
```

Mở http://localhost:5173.

## Build riêng để deploy S3/CloudFront

Backend chạy độc lập trên EC2 bằng `../docker-compose.backend.yml`. Trong thư mục
`frontend/`, build với URL HTTPS thực tế của backend:

```bash
pnpm install --frozen-lockfile
VITE_API_URL=https://api.example.com VITE_USE_MOCK=false pnpm build
```

`VITE_API_URL` là origin của API, không thêm `/api` vì client đã thêm đường dẫn này.
Biến được nhúng vào bundle khi build; đổi URL cần build và upload lại.
Không đặt secret trong biến `VITE_*`.

Upload nội dung `dist/` lên S3 origin của CloudFront, đặt default root object là
`index.html`, và cấu hình SPA fallback về `index.html` cho đường dẫn React Router.
Khi cập nhật bản build, invalidate cache CloudFront để nhận bản mới.
Không cần chạy container frontend/nginx trên EC2.

Nếu frontend phục vụ qua HTTPS, API cũng phải có URL HTTPS để tránh mixed content.

## Lệnh khác

```bash
pnpm lint     # oxlint + prettier --check
pnpm format   # prettier --write
pnpm test     # vitest
pnpm build    # tsc + vite build → dist/
```

## Cấu trúc

```
src/
├── api/          client.ts (envelope + ApiError), jobs.ts (poll / cancel), proposals.ts, types.ts (mirror contract), *.ts (endpoint modules)
├── hooks/        useConnections, useConversations, useSendMessage (job + polling live state), useTools, useActiveConnection
├── pages/        ChatPage (Diagnose), ProposalsPage, ConnectPage, ToolsPage, ChecklistPage (placeholder), HomeRedirect
├── components/   layout/ (AppShell, Sidebar, HeaderBar, PageHeader, Panel), connections/ (ConnectionsTable, …), chat/ (DiagnosisCard, ToolCallTimeline, ConversationList, …), remediation/ (ProposalCard), ui/ (shadcn + status-tag, table)
├── lib/          strings.ts (mọi text UI – tiếng Anh), toolIcons.ts (group → icon), format.ts, utils.ts
└── mocks/        MSW handlers + scripted job scenarios (bật bằng VITE_USE_MOCK=true)
```

Quy ước: text UI tiếng Anh, gom trong `src/lib/strings.ts`; nội dung câu trả lời của agent (tiếng Việt) đến từ backend và hiển thị nguyên văn. Kiểu API chỉ khai báo ở `src/api/types.ts`.

Mock: tên kết nối chứa chữ "fail" sẽ giả lập verify thất bại.

## Đăng nhập Cognito

Xem [cấu hình Cognito, cách ly `user_id` và migration dữ liệu cũ](../docs/AUTH.md). Mặc định `AUTH_MODE=cognito`; EC2 cần `COGNITO_ISSUER`, `COGNITO_CLIENT_ID`, `COGNITO_DOMAIN`. Dev offline đặt `AUTH_MODE=none` cùng `APP_ENV=dev`, `RUNTIME=local`. Frontend lấy cấu hình công khai từ API, không cần biến Vite riêng cho Cognito.
