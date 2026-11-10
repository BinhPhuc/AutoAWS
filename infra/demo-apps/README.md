# Mock app cho các kịch bản (chỉ dev/test)

App giả lập dùng trong kịch bản, **không phải một phần của AutoAWS**. Chỉ dùng thư viện chuẩn của Python
(chạy được với Python 3.9 có sẵn trên Amazon Linux 2023), cấu hình bằng biến môi trường.

| File | Kịch bản | Bản khoẻ | Bản lỗi |
|---|---|---|---|
| `orders_api.py` | KB7 | v2.4.x: mọi request trả 200 | v2.5.x: `/api/*` kết nối DB `10.70.9.15:5432` → timeout, log traceback `OperationalError`, trả 500 |
| `web_health.py` | KB3 | v1.x: health check ở `/health` | v2.x: đổi sang `/api/health`, `/health` trả 404 (target group báo unhealthy), `/` vẫn 200 |

Phiên bản đọc lại từ file `APP_VERSION_FILE` ở **mỗi request** — "deploy" = ghi số phiên bản vào file đó.

## Trên AWS

Không cần làm gì thêm: `infra/aws-scenarios/scenario.py up kb3|kb7` chèn file vào UserData của instance
(dòng `#@include` trong template), cài thành service systemd, CloudWatch Agent đẩy `/var/log/app.log` lên
CloudWatch Logs. `fault` / `fix` đổi phiên bản qua SSM Run Command.
Xem template đã chèn code: `backend/.venv/bin/python infra/aws-scenarios/scenario.py render kb7`.

## Trên máy

```bash
# KB7: chạy bản khoẻ ở cổng 8081, log ra màn hình
APP_PORT=8081 APP_VERSION_FILE=/tmp/orders.version APP_LOG_FILE=- DB_TIMEOUT=1 \
  python3 infra/demo-apps/orders_api.py
echo 2.5.0 > /tmp/orders.version          # "deploy" bản lỗi
curl -i localhost:8081/api/orders         # 500, log có traceback
echo 2.4.3 > /tmp/orders.version          # rollback

# KB3
APP_PORT=8082 APP_VERSION_FILE=/tmp/web.version APP_LOG_FILE=- python3 infra/demo-apps/web_health.py
echo 2.0.0 > /tmp/web.version && curl -i localhost:8082/health   # 404
```

Đẩy log của `orders_api.py` vào CloudWatch Logs của **LocalStack** (để AutoAWS đọc bằng `logs_insights_query`):

```bash
AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE \
AWS_SECRET_ACCESS_KEY=localstack-secret-key AWS_DEFAULT_REGION=ap-southeast-1 \
LOG_GROUP=/demo/orders-api-local APP_PORT=8081 APP_VERSION_FILE=/tmp/orders.version APP_LOG_FILE=- \
  backend/.venv/bin/python infra/demo-apps/orders_api.py      # cần boto3 → dùng venv của backend
```

| Biến | Mặc định (giá trị trên EC2) |
|---|---|
| `APP_PORT` | `80` (cổng < 1024 cần root khi chạy trên máy → đổi sang 8081…) |
| `APP_VERSION_FILE` | `/opt/app/VERSION` (không có file → `APP_VERSION`) |
| `APP_VERSION` | `2.4.3` (orders_api) / `1.4.2` (web_health) |
| `APP_LOG_FILE` | `/var/log/app.log` (`-` = stdout) |
| `DB_HOST`, `DB_PORT`, `DB_TIMEOUT` | `10.70.9.15`, `5432`, `3` (chỉ orders_api) |
| `LOG_GROUP` | rỗng; đặt thì gửi thêm từng dòng log lên CloudWatch Logs bằng boto3 (chỉ orders_api) |
