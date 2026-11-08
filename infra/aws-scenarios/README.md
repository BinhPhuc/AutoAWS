# Kịch bản KB1–KB7 trên AWS thật (CloudFormation) — chỉ dev/test

Dựng 7 kịch bản của Bảng 2.14 (báo cáo tiến độ lần 2) trong **tài khoản AWS dùng để test**.
Script **tạo và sửa tài nguyên thật, có tốn tiền** — không phải một phần của app AutoAWS (app vẫn chỉ đọc).
Không chạy trên tài khoản production.

Cách làm: CloudFormation dựng bản **khoẻ**, sau đó `fault` cài sự cố bằng API, nhờ vậy CloudTrail ghi lại
"ai đổi gì, lúc nào" — đúng loại bằng chứng mà các kịch bản cần.

| KB | Stack dựng | `fault` làm gì |
|---|---|---|
| KB1 | `web-server`, route table public + một route table không có đường ra Internet | Gắn subnet sang route table không có đường ra (`ReplaceRouteTableAssociation`) |
| KB2 | `app-server` chạy Docker ở 8080, SG **không** mở 8080, bản ghi `app.<domain>` trỏ IP hiện tại | Stop/start instance → IP đổi, bản ghi A vẫn trỏ IP cũ |
| KB3 | ALB + 2 instance ở 2 AZ, health check `/health`, alarm `UnHealthyHostCount`, log `/demo/kb3-web` | "Deploy" v2 qua SSM Run Command: v2 chỉ còn `/api/health` → 2/2 target unhealthy, web vẫn chạy |
| KB4 | `api-server`, một NACL chặn cổng 1024–65535 chiều ra (chưa gắn) | Gắn NACL đó vào subnet → SSH treo |
| KB5 | `worker-01` trong subnet không tự gán public IP | — (sự cố có sẵn trong stack) |
| KB6 | `bastion`, SG chỉ mở 22 cho IP cũ `203.0.113.10/32` | — (sự cố có sẵn trong stack) |
| KB7 | `orders-api` v2.4.3, log `/demo/kb7-orders-api` | "Deploy" v2.5.0 qua SSM: không kết nối được DB → mọi request 500, log có stack trace |

## Cần chuẩn bị

- Tài khoản AWS test, credentials có quyền tạo VPC/EC2/IAM/ELB/Route 53/CloudWatch (ví dụ profile `autoaws-test`).
- Python có `boto3`: dùng luôn `backend/.venv`.
- **KB2**: một tên miền của bạn đã có **public hosted zone** trên Route 53 (mua tên miền qua Route 53 thì zone tự có).
- Tuỳ chọn: một EC2 key pair (`--key-name`) nếu muốn tự thử SSH.

## Chạy

```bash
PY=backend/.venv/bin/python
S=infra/aws-scenarios/scenario.py
OPTS="--profile autoaws-test --region ap-southeast-1"

$PY $S up kb1 $OPTS                    # dựng stack autoaws-kb1 (3–5 phút), hỏi xác nhận trước
$PY $S fault kb1 $OPTS                 # đợi 2–3 phút sau `up` cho instance khởi động rồi mới cài lỗi
$PY $S status kb1 $OPTS                # xem output (ID tài nguyên)
$PY $S fix kb1 $OPTS                   # gỡ lỗi (tuỳ chọn)
$PY $S down kb1 $OPTS                  # gỡ lỗi + xoá stack — NHỚ chạy sau khi test xong
$PY $S down all $OPTS                  # xoá mọi stack autoaws-kb*

$PY $S up kb2 $OPTS --param HostedZoneId=Z0123456789ABC --param DomainName=example.com
```

Sau đó cho AutoAWS đọc tài khoản test: tạo kết nối Role (deploy template CloudFormation mà app sinh ra,
`AutoAWS-ReadOnly`) hoặc Access Key (dev), rồi hỏi câu của kịch bản — hoặc chấm điểm tự động:

```bash
$PY infra/eval/run_eval.py --answers infra/aws-scenarios/answers.aws.json --runs 5
```
`answers.aws.json` (gitignore) chứa câu hỏi + nguyên nhân kỳ vọng với ID tài nguyên thật, do `up`/`fault` ghi.

## Lưu ý

- **Thời gian**: sự kiện CloudTrail hiện sau 5–15 phút; metric/alarm của KB3 cần 1–3 phút; SSM Agent cần vài phút
  mới Online (bước `fault` của KB3/KB7 tự đợi). Hỏi AutoAWS sau khi đã đợi.
- **Chi phí** (ước tính, xoá trong ngày thì vài cent đến dưới 1 USD): EC2 t3.micro, public IPv4 (~0,005 USD/giờ/IP),
  ALB của KB3 (~0,02 USD/giờ) nằm trong free tier kiểu cũ; **hosted zone 0,50 USD/tháng và tên miền không miễn phí**.
  Tài khoản tạo sau 15/07/2025 dùng gói credit thay free tier 12 tháng — kiểm tra trang Free Tier của tài khoản.
  Stack được gắn tag `Project=autoaws-demo`; nên bật AWS Budgets.
- **Luôn `down`** sau khi test. `down` gỡ lỗi trước (NACL tự tạo không xoá được khi còn gắn subnet).
- **Bảo mật**: KB1/KB2/KB4/KB5 mở 22 cho `0.0.0.0/0` vì đó là nội dung kịch bản; instance không có dữ liệu,
  nhưng đừng để stack chạy lâu. KB1 có tham số `SshCidr` để thu hẹp.
- **LocalStack**: script có `--endpoint-url http://localhost:4566` để thử nhanh, nhưng CloudFormation của LocalStack
  Community không tạo rule SG/NACL và không có ALB, UserData không chạy — kết quả không đúng như AWS.
  Mô phỏng trên LocalStack dùng `infra/localstack/seed.py`.
- Template đã kiểm bằng `cfn-lint` (`pip install cfn-lint; cfn-lint infra/aws-scenarios/templates/*.yaml`).
