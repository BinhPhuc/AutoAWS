# LocalStack — môi trường mẫu để test AutoAWS (chỉ dev)

Dựng các kịch bản sự cố trong LocalStack để chạy AutoAWS end-to-end mà không cần tài khoản AWS.
Script **tạo** tài nguyên nên chỉ chạy với LocalStack (tự từ chối endpoint khác). App AutoAWS vẫn chỉ đọc.

```bash
docker start <container-localstack>          # LocalStack 4.x Community, cổng 4566
backend/.venv/bin/python infra/localstack/seed.py
```

| Kịch bản | Dựng gì | Câu hỏi thử |
|---|---|---|
| KB1 | `web-server` trong subnet bị chuyển sang route table không có 0.0.0.0/0 → IGW; SG mở 22 | "Tôi không SSH được vào instance web-server…" |
| KB2 | `app-server`, SG thiếu 8080, Route 53 `app.autoaws-demo.com` trỏ IP cũ | "…đã trỏ app.autoaws-demo.com về EC2 nhưng không vào được." |
| KB3 | Bỏ qua: LocalStack Community không có ELBv2 / CloudTrail | — |

Chạy backend trỏ vào LocalStack, LLM do một MCP client đóng vai:

```bash
cd backend
LLM_PROVIDER=mcp AWS_ENDPOINT_URL=http://localhost:4566 PLATFORM_AWS_ACCOUNT_ID=000000000000 \
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE AWS_SECRET_ACCESS_KEY=localstack-secret-key \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Trong app: tạo kết nối Access Key `AKIAIOSFODNN7EXAMPLE` / secret bất kỳ ≥16 ký tự, region `ap-southeast-1`.
Kết nối Role: lấy template CloudFormation từ app, deploy vào LocalStack, dán `arn:aws:iam::000000000000:role/AutoAWSReadOnly`.

Giới hạn của LocalStack Community: không kiểm tra IAM (thiếu quyền chỉ lộ ra trên AWS thật — có `tests/test_policy.py` bù),
không có ELBv2/CloudTrail, `ssm:DescribeInstanceInformation` chưa được emulate, DNS của LocalStack không phục vụ bản ghi Route 53.
