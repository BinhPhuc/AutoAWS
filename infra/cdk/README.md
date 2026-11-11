# Hạ tầng nền tảng AutoAWS (CDK) — triển khai serverless theo báo cáo

App CDK (Python) dựng tài khoản **nền tảng** AutoAWS theo §2.2–§2.9 và Bảng 2.12 của báo cáo tiến độ lần 2.
**Trạng thái: synth + cfn-lint + test đạt; chưa deploy lần nào** (chưa có tài khoản AWS).

```
Trình duyệt ─► CloudFront ─┬─► S3 (giao diện React, OAC)
                           └─► /api/* ─► API Gateway HTTP API ─► Lambda api-handler (FastAPI + Mangum)
                                                                   │ invoke (Event / RequestResponse)
                                                                   ▼
            Bedrock (Mantle) ◄── Lambda agent-worker ──► STS AssumeRole AutoAWSReadOnly (tài khoản khách)
                                   │ StartExecution
                                   ▼
            Step Functions remediation-flow: SNS → chờ duyệt (task token, 24 h) → Recheck → Execute → Verify → SNS
                                                                        │
                                   Lambda action-executor ──► STS AssumeRole AutoAWSRemediation (chỉ khi đã duyệt)
            DynamoDB (1 bảng, KMS CMK, PITR, TTL) dùng chung
```

| Stack (`AutoAws-<envName>-…`) | Tài nguyên |
|---|---|
| `Data` | Bảng DynamoDB (single-table như `backend/app/storage/dynamo.py`), KMS key xoay vòng, PITR, TTL `ttl` |
| `Auth` | Cognito User Pool (gói **Lite**, email đăng nhập, tự đăng ký `selfSignUp`, MFA TOTP tuỳ chọn), domain Hosted UI (`autodiag-<env>-<account>`, đổi bằng `authDomainPrefix` — tiền tố không được chứa `aws` / `amazon` / `cognito`), app client public (code + PKCE, không secret) |
| `Agent` | Lambda `agent-worker` (role `autoaws-agent-worker`: AssumeRole chỉ `AutoAWSReadOnly`, `bedrock-mantle:CreateInference` giới hạn model, reserved concurrency 5, async retry 0), Lambda `action-executor` (role `autoaws-action-executor`: AssumeRole `AutoAWSRemediation` + `AutoAWSReadOnly`, Deny Bedrock) |
| `Workflow` | State machine `autoaws-remediation-flow` (Standard), SNS topic + email |
| `Api` | HTTP API (throttle 20 rps / burst 40) → Lambda `api-handler` (Deny `sts:AssumeRole`: không chạm tài khoản khách) |
| `Frontend` | S3 riêng tư + CloudFront (OAC, SPA fallback bằng CloudFront Function chỉ cho phần giao diện — lỗi 403/404 của API giữ nguyên, `/api/*` → HTTP API cùng origin) |
| `Ops` | Alarm lỗi / throttle của 3 Lambda + flow thất bại, AWS Budgets 20 USD |

Mọi route của HTTP API cần access token Cognito (JWT authorizer) **trừ** `GET /api/health` và `GET /api/auth/config`.
Callback / logout URL của app client = URL CloudFront (hoặc `frontendUrl` nếu gắn tên miền riêng) + `http://localhost:5173` khi `envName=dev`.

**Một lần `cdk deploy --all` là đủ.** CloudFront cần domain của HTTP API, Cognito cần URL CloudFront (callback), authorizer của API cần client Cognito — nếu HTTP API nằm trọn trong stack Api thì ba thứ này thành vòng. Vì vậy HTTP API (rỗng: chưa có stage, route) được tạo trong stack Frontend, và thứ tự là một đường thẳng (CDK tự sắp):
`Data`, `Frontend` (CloudFront + HTTP API rỗng) → `Auth` (callback = URL CloudFront) → `Agent` → `Workflow` → `Api` (Lambda, stage, route, JWT authorizer gắn vào HTTP API đã có) → `Ops`.

## Deploy (khi có tài khoản)

Hướng dẫn đầy đủ từng bước (chuẩn bị, `cdk.json`, deploy, tạo người dùng, kết nối tài khoản khách, chi phí, lỗi hay gặp): [README gốc, mục Triển khai lên AWS](../../README.md#triển-khai-lên-aws). Tóm tắt:

```bash
cd infra/cdk
python3 -m venv .venv && .venv/bin/pip install "aws-cdk-lib>=2.200,<3" "constructs>=10" pytest
./build_lambda.sh                                    # backend/app + deps (Python 3.12, x86_64) → build/lambda
(cd ../../frontend && VITE_USE_MOCK=false VITE_API_URL= pnpm build)   # có frontend/dist thì deploy luôn giao diện
export AWS_PROFILE=autoaws-platform AWS_REGION=ap-southeast-1
npx aws-cdk@2 bootstrap                              # một lần cho tài khoản/region
npx aws-cdk@2 deploy --all -c notificationEmail=team@example.com -c alarmEmail=ops@example.com
# xong: mở output AutoAws-dev-Frontend.Url
```

Trước khi chạy thật:
- **Bedrock**: bật quyền dùng model Claude trong region (biểu mẫu Anthropic lần đầu); model mặc định `anthropic.claude-opus-5-5`, dự phòng khi bị từ chối `anthropic.claude-opus-4-8` (`-c bedrockModelId=… -c bedrockFallbackModel=…`).
- **Template của khách**: api-handler sinh template với trust chỉ tới `autoaws-agent-worker` / `autoaws-action-executor` của tài khoản này (`PLATFORM_*_ROLE_ARN`).
- **SNS**: người nhận phải bấm xác nhận email đăng ký.
- Context khác (`cdk.json`): `envName` (dev / demo), `agentConcurrency`, `budgetUsd`, `llmEffort`, `destroyData` (dev mặc định xoá bảng khi xoá stack).

## Kiểm tra trên máy (không cần AWS)

```bash
CDK_DEFAULT_REGION=ap-southeast-1 CDK_DEFAULT_ACCOUNT=111122223333 .venv/bin/python app.py   # → cdk.out/
../../backend/.venv/bin/cfn-lint cdk.out/*.template.json                                       # chỉ W3005 (CDK tự sinh)
.venv/bin/pytest                                                                               # tính chất bảo mật + cấu hình
```
