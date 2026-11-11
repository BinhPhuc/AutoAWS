# Cognito cho AutoAWS hiện tại

Template [`cognito.yaml`](cognito.yaml) tạo Cognito độc lập trong **tài khoản nền tảng
AutoAWS**, dùng được khi backend/frontend chạy localhost hoặc triển khai bản
backend EC2 + frontend S3/CloudFront. Cấu hình bám theo
`infra/cdk/autoaws_cdk/auth.py` và hợp đồng `docs/API_CONTRACT.md` §0.1:

- User Pool gói Lite, đăng nhập bằng email, xác minh email và khôi phục mật khẩu qua email.
- Hosted UI classic, app client public **không có client secret**, OAuth Authorization
  Code; frontend hiện có gửi PKCE S256. Scope: `openid email profile`.
- Callback `<FrontendUrl>/auth/callback`, logout `<FrontendUrl>/`; mặc định dùng Vite
  tại `http://localhost:5173`, không cần có CloudFront.
- Mật khẩu tối thiểu 12 ký tự, có chữ hoa, chữ thường và số; MFA TOTP tuỳ chọn.
- Access/ID token sống 1 giờ, refresh token 7 ngày, bật token revocation.

Template chỉ tạo User Pool, domain và app client. Backend hiện kiểm chữ ký JWT bằng
JWKS công khai; không cần Identity Pool hay quyền Cognito trong IAM role runtime EC2.
Đây là stack độc lập, không tự kết nối với các Lambda/API Gateway của CDK. Nếu đã dùng
stack CDK `Auth`, tiếp tục dùng Outputs của stack đó để giữ nguyên người dùng và cấu hình.

## 1. Tạo stack trên AWS Console

1. Chọn tài khoản nền tảng và region, ví dụ `ap-southeast-1`.
2. CloudFormation → **Create stack** → **With new resources (standard)** →
   **Upload a template file** → chọn `infra/cloudformation/cognito.yaml`.
3. Stack name ví dụ `autoaws-auth`. Điền tham số:

| Tham số | Giá trị |
|---|---|
| `EnvironmentName` | `dev` hoặc `demo`, `staging`, `prod` |
| `FrontendUrl` | Mặc định `http://localhost:5173` để test local; chấp nhận `http://localhost` với port khác hoặc origin HTTPS khi triển khai, ví dụ `https://d123example.cloudfront.net`. Không thêm `/`, path hay query |
| `DomainPrefix` | Để trống để dùng `autodiag-<environment>-<account>`, hoặc nhập prefix riêng chưa được sử dụng |
| `AllowLocalhost` | Mặc định `false`; đặt `true` để thêm `http://localhost:5173` khi `FrontendUrl` là origin khác. Không cần bật khi dùng `FrontendUrl` mặc định; URL trùng chỉ được khai báo một lần |
| `SelfSignUp` | `true` cho phép tự đăng ký; `false` nếu chỉ quản trị viên tạo tài khoản |

4. Tạo stack và chờ `CREATE_COMPLETE`, sau đó mở tab **Outputs**.

Prefix domain chỉ chứa chữ thường, số và dấu `-` ở giữa; không chứa `aws`, `amazon`
hay `cognito`. Không dùng `autoaws-...` làm prefix. Nếu domain đã tồn tại, chọn prefix
khác. Template dùng domain mặc định của Cognito trong các AWS Region thương mại;
không cần Route 53 hoặc chứng chỉ ACM riêng.

## 2. Cấu hình backend

Tự cập nhật `backend/.env` bằng Outputs của stack:

```dotenv
AUTH_MODE=cognito
COGNITO_USER_POOL_ID=<UserPoolId>
COGNITO_CLIENT_ID=<WebClientId>
COGNITO_DOMAIN=<HostedUiUrl>
# Bắt buộc khi AUTH_MODE=cognito: khoá ký External ID của kết nối IAM role.
# Tạo một lần, giữ cố định: python -c "import secrets; print(secrets.token_hex(32))"
EXTERNAL_ID_SECRET=<chuỗi ngẫu nhiên dài>
```

`COGNITO_DOMAIN` là URL đầy đủ `https://<prefix>.auth.<region>.amazoncognito.com`,
không thêm `/login`, `/oauth2/authorize` hay dấu `/` cuối. Backend suy ra issuer và
region từ User Pool ID; không cần biến `COGNITO_REGION` hay client secret.
Cấu hình DynamoDB và credentials nền tảng hiện có giữ nguyên.

Từ thư mục gốc repo, tạo lại container để nạp biến môi trường mới:

```bash
docker compose -f docker-compose.backend.yml up -d --build --force-recreate backend
```

Nếu chạy trực tiếp bằng Uvicorn, khởi động lại tiến trình sau khi cập nhật cấu hình.
`RUNTIME=local` vẫn đúng khi backend chạy EC2; Cognito không yêu cầu đổi sang Lambda.

Frontend gọi `GET /api/auth/config` để lấy domain/client/scopes. **Không cần thêm
biến Cognito vào frontend.** Khi API khác origin, build như hướng dẫn hiện có:

```bash
# Chạy trong frontend/; thay bằng URL HTTPS thật của API.
VITE_API_URL=https://api.example.com VITE_USE_MOCK=false pnpm build
```

Lệnh trên dùng cú pháp Bash (ví dụ terminal EC2). Với PowerShell:

```powershell
$env:VITE_API_URL = 'https://api.example.com'
$env:VITE_USE_MOCK = 'false'
pnpm build
```

Nếu API đi qua CloudFront cùng origin tại `/api/*`, để `VITE_API_URL` trống.
Compose EC2 hiện ép `CORS_ORIGINS=*`; nếu chạy backend trực tiếp hoặc dùng Compose
khác, cấu hình CORS cho origin frontend và header `Authorization`.

## 3. Chạy thử trên localhost

Tạo hoặc **Update stack hiện có** bằng template mới với `FrontendUrl=http://localhost:5173`.
Có thể giữ `AllowLocalhost=false`: callback và logout local đã được tạo từ
`FrontendUrl`. Cognito vẫn chạy trên AWS thật; chỉ backend và frontend chạy trên máy.
Theo [tài liệu AWS](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html),
Cognito cho phép callback HTTP tại localhost để kiểm thử.

Điền ba biến `COGNITO_*` và `AUTH_MODE=cognito` như mục 2 vào `backend/.env`.
Để thử đăng nhập mà chưa cần DynamoDB hay Bedrock, có thể đặt thêm:

```dotenv
RUNTIME=local
STORAGE_BACKEND=sqlite
DB_PATH=./autoaws.db
LLM_PROVIDER=mock
FRONTEND_URL=http://localhost:5173
```

Trong `frontend/.env`, dùng backend thật qua proxy có sẵn của Vite:

```dotenv
VITE_API_URL=
VITE_USE_MOCK=false
```

Chạy hai terminal sau khi đã cài dependencies:

```bash
# Terminal 1, từ thư mục backend/ và đã kích hoạt virtualenv
uvicorn app.main:app --reload --port 8000
```

```bash
# Terminal 2, từ thư mục frontend/
pnpm dev --port 5173 --strictPort
```

Mở đúng `http://localhost:5173` → **Sign in** → đăng ký/xác minh email nếu chưa có
tài khoản → quay về `http://localhost:5173/auth/callback`. Thử **Sign out** và đăng
nhập lại. Vite proxy `/api` đến backend port 8000 nên không cần thay CORS cho luồng này.
`--strictPort` tránh Vite tự chuyển port làm sai callback đã đăng ký.
Nếu muốn port khác, sửa `FrontendUrl` và port Vite cho khớp. Dùng hostname `localhost`,
không mở bằng `127.0.0.1` vì frontend tạo callback theo origin trình duyệt.

Có thể kiểm tra backend trước khi đăng nhập:

```bash
curl http://localhost:8000/api/auth/config
curl -i http://localhost:8000/api/me
```

Request đầu phải có `data.mode="cognito"`; request thứ hai phải trả `401` khi chưa
có token. Sau khi đăng nhập, request `/api/me` từ frontend phải trả `200`.

## 4. CloudFront và kiểm tra đăng nhập

- `/auth/callback?code=...&state=...` phải tải được React `index.html`, giữ query
  string trong URL trình duyệt. Cấu hình SPA rewrite ở viewer request cho phần giao
  diện; nếu có `/api/*` trên cùng distribution thì không rewrite các request API.
- Không cache `/api/auth/config` và các API có xác thực. Nếu gọi API qua CloudFront,
  chuyển tiếp `Authorization` đến backend.
- Frontend và API công khai phải dùng HTTPS; `http://localhost:5173` chỉ dành cho dev.

Kiểm tra qua URL HTTPS công khai của API (hoặc cùng domain CloudFront):

```bash
curl https://api.example.com/api/auth/config
curl -i https://api.example.com/api/me
```

Request đầu phải trả envelope thành công với `data.mode="cognito"`, domain/client ID
khớp Outputs và đủ ba scope. Request `/api/me` khi chưa có token phải trả `401`.
Mở frontend → **Sign in** → **Sign up**, xác nhận mã email → quay lại AutoAWS. Tạo
một Connection/hội thoại và thử **Sign out** rồi đăng nhập lại. Nếu `SelfSignUp=false`,
tạo người dùng trong Cognito Console → User pool → **Users** → **Create user**, rồi
đăng nhập bằng mật khẩu tạm và đổi mật khẩu theo hướng dẫn Hosted UI.

Khi bật auth, dữ liệu cũ thuộc người dùng `local` không tự chuyển sang Cognito `sub`;
tạo Connection/hội thoại mới sau khi đăng nhập. Cognito chỉ xác thực người sử dụng
AutoAWS; kết nối AWS bằng role/access key vẫn được tạo riêng trong trang **Connect**.

| Triệu chứng | Cách kiểm tra |
|---|---|
| `redirect_mismatch` | `FrontendUrl` phải đúng origin đang mở; callback có `/auth/callback`, không có `/` cuối; nếu origin chính khác localhost thì bật `AllowLocalhost=true` để thêm `http://localhost:5173` |
| `/auth/callback` trả 403/404 hoặc XML của S3 | Sửa SPA rewrite CloudFront, upload đủ bản build frontend |
| UI vẫn không yêu cầu đăng nhập | Kiểm tra `/api/auth/config`, recreate backend, tắt mock và bỏ cache API |
| API trả 401 sau khi đăng nhập | Kiểm tra pool/client ID, token gửi là **access token**, và proxy chuyển tiếp `Authorization` |
| Không nhận được email xác minh | Kiểm tra spam, email đã nhập và quota gửi email Cognito; dùng SES khi nhu cầu vượt cấu hình email mặc định |

## 5. Cập nhật và giữ tài khoản

Khi đổi domain frontend, **Update stack hiện có** với `FrontendUrl` mới. Template
thay danh sách callback/logout tương ứng; nếu còn mở origin cũ thì không đăng nhập
được từ origin đó. Update backend khi domain Cognito hoặc client ID thay đổi.

User Pool bật deletion protection và `DeletionPolicy: Retain`/`UpdateReplacePolicy:
Retain`. Xoá stack vẫn giữ pool/người dùng, nhưng domain và app client bị xoá nên ứng
dụng không còn đăng nhập được. Khi dọn demo hoàn toàn, phải chủ động tắt deletion
protection và xoá pool giữ lại trong Cognito Console. Đổi sang pool mới làm đổi
`sub`; dữ liệu AutoAWS không tự di chuyển giữa các pool.

Kiểm chứng cục bộ: `cfn-lint infra/cloudformation/cognito.yaml`. Việc lint không thay
thế kiểm tra Hosted UI, email và đăng nhập trên tài khoản AWS thật.

## Tham khảo

- [CloudFormation User Pool](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-userpool.html)
- [CloudFormation app client](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-userpoolclient.html)
- [Hosted UI classic và managed login](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-userpooldomain.html)
- [Authorization endpoint, callback và PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html)
- [Cognito domain prefix](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-assign-domain-prefix.html)
