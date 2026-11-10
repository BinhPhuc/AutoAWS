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
| `Auth` | Cognito User Pool, xác minh email, public SPA client, Hosted UI domain; outputs Issuer / ClientId / DomainUrl |
| `Data` | Bảng DynamoDB (single-table như `backend/app/storage/dynamo.py`), KMS key xoay vòng, PITR, TTL `ttl` |
| `Agent` | Lambda `agent-worker` (role `autoaws-agent-worker`: AssumeRole chỉ `AutoAWSReadOnly`, `bedrock-mantle:CreateInference` giới hạn model, reserved concurrency 5, async retry 0), Lambda `action-executor` (role `autoaws-action-executor`: AssumeRole `AutoAWSRemediation` + `AutoAWSReadOnly`, Deny Bedrock) |
| `Workflow` | State machine `autoaws-remediation-flow` (Standard), SNS topic + email |
| `Api` | HTTP API (throttle 20 rps / burst 40) → Lambda `api-handler` (Deny `sts:AssumeRole`: không chạm tài khoản khách) |
| `Frontend` | S3 riêng tư + CloudFront (OAC, SPA fallback, `/api/*` → HTTP API cùng origin) |
| `Ops` | Alarm lỗi / throttle của 3 Lambda + flow thất bại, AWS Budgets 20 USD |

Stack **Auth** tạo Cognito User Pool + public client (code + PKCE), domain, callback/logout URLs theo `frontendUrl`; API dùng JWT authorizer + scope `openid`. Backend kiểm JWT độc lập. Xem [đăng nhập và migration](../../docs/AUTH.md).

## Deploy (khi có tài khoản)

```bash
cd infra/cdk
python3 -m venv .venv && .venv/bin/pip install "aws-cdk-lib>=2.200,<3" "constructs>=10" pytest
./build_lambda.sh                                    # backend/app + deps (Python 3.12, x86_64) → build/lambda
(cd ../../frontend && pnpm build)                    # tuỳ chọn: có frontend/dist thì deploy luôn giao diện
export AWS_PROFILE=autoaws-platform AWS_REGION=ap-southeast-1
npx aws-cdk@2 bootstrap                              # một lần cho tài khoản/region
npx aws-cdk@2 deploy --all -c notificationEmail=team@example.com -c alarmEmail=ops@example.com
# sau lần đầu: lấy URL CloudFront (output Frontend.Url) rồi deploy lại để link trong email đúng
npx aws-cdk@2 deploy --all -c frontendUrl=https://dxxxx.cloudfront.net
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
