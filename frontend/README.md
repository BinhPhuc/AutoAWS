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
├── api/          client.ts (envelope + ApiError), sse.ts (POST + ReadableStream), types.ts (mirror contract), *.ts (endpoint modules)
├── hooks/        useConnections, useConversations, useSendMessage (SSE live state), useTools, useActiveConnection
├── pages/        ConnectPage, ChatPage, ChecklistPage (placeholder), HomeRedirect
├── components/   layout/ (AppShell, Sidebar, …), connections/, chat/ (DiagnosisCard, ToolCallTimeline, …), ui/ (shadcn)
├── lib/          strings.ts (mọi text UI – tiếng Anh), toolIcons.ts (group → icon), format.ts, utils.ts
└── mocks/        MSW handlers + SSE fixtures (bật bằng VITE_USE_MOCK=true)
```

Quy ước: text UI tiếng Anh, gom trong `src/lib/strings.ts`; nội dung câu trả lời của agent (tiếng Việt) đến từ backend và hiển thị nguyên văn. Kiểu API chỉ khai báo ở `src/api/types.ts`.

Mock: tên kết nối chứa chữ "fail" sẽ giả lập verify thất bại.
