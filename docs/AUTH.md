# Đăng nhập và phân vùng dữ liệu

AutoAWS dùng Cognito User Pool làm nguồn tài khoản: đăng ký email, xác minh email, đăng nhập và đặt lại mật khẩu qua Hosted UI. Không lưu mật khẩu trong database ứng dụng. `user_id` trong database là claim `sub` ổn định của Cognito, không dùng email làm khoá.

## Cấu hình EC2 + CloudFront

1. Tạo User Pool và public app client **không có client secret**, bật Authorization Code, scopes `openid email profile`, thêm Cognito domain. Có thể deploy riêng stack `AutoAws-<env>-Auth` trong `infra/cdk/` sau bước cài CDK/build asset theo README hạ tầng; context `frontendUrl` phải là origin thật của giao diện.
2. Callback URL: `https://<frontend>/auth/callback`. Allowed sign-out URL: `https://<frontend>` (không dấu `/` cuối). Dev dùng `http://localhost:5173` tương ứng. Frontend cần HTTPS ngoài localhost để chạy PKCE/Web Crypto.
3. Điền `backend/.env` từ output stack Auth:

   ```dotenv
   AUTH_MODE=cognito
   COGNITO_ISSUER=https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_EXAMPLE
   COGNITO_CLIENT_ID=<Auth.ClientId>
   COGNITO_DOMAIN=https://<Auth-domain>.auth.ap-southeast-1.amazoncognito.com
   ```

4. Khởi động lại backend. FE tự lấy cấu hình công khai từ `/api/auth/config`, không cần build lại khi thay User Pool. CloudFront phải chuyển tiếp `Authorization` cho `/api/*`, tắt cache API, và phục vụ `index.html` tại `/auth/callback`.
5. Vào giao diện → **Sign in or create account** → đăng ký, xác minh email → đăng nhập → kết nối AWS. Cognito giữ tài khoản; DynamoDB chỉ lưu dữ liệu nghiệp vụ kèm `user_id`.

CDK tạo stack Auth + JWT authorizer cho API Gateway, giữ public đúng hai GET health/config. Backend vẫn tự kiểm JWT nên EC2 không cần dựa vào authorizer. Lần deploy CDK đầu chưa biết CloudFront URL: Auth dùng callback localhost; lấy `Frontend.Url`, deploy lại với `-c frontendUrl=https://dxxx.cloudfront.net` để bật đăng nhập trên domain thật, tránh phụ thuộc vòng giữa các stack.

## Phiên và cách ly

- Code + PKCE S256, kiểm `state` qua `oidc-client-ts`. Chỉ giao dịch PKCE tạm thời nằm trong sessionStorage; access/ID/refresh token ở bộ nhớ, không localStorage. Tải lại trang cần bấm đăng nhập lại (phiên Cognito thường không yêu cầu nhập lại mật khẩu).
- FE gia hạn access token trước request khi còn dưới 30 giây; dùng một request refresh chung khi gọi API đồng thời. 401/gia hạn thất bại → đóng giao diện nghiệp vụ, xoá query cache. Logout thu hồi refresh token, xoá phiên và chuyển Cognito `/logout`. JWT đã phát hành có thể còn hợp lệ đến khi hết hạn (CDK đặt 15 phút).
- Backend kiểm chữ ký RS256 từ JWKS cache có hỗ trợ đổi key, `iss`, `exp`, `iat`, `token_use=access`, `client_id`, `scope=openid` và `sub`. Không tin `X-User-Id` hoặc `user_id` do client gửi.
- Mỗi Store gắn với một người dùng. SQLite có cột/index `user_id` trên sáu bảng. DynamoDB có `user_id` trên item và tool call nhúng, PK/GSI1PK mang tiền tố `USER#<sub>#`. Index ById luôn kiểm lại chủ sở hữu.
- Job, Lambda invoke, Step Functions và task nền local truyền người sở hữu từ dữ liệu đã xác thực. Handler nội bộ thiếu user ID bị từ chối. Khôi phục đề xuất khi backend local khởi động lại chạy riêng từng chủ sở hữu.
- `AUTH_MODE=none` chỉ được phép khi `APP_ENV=dev|test`, `RUNTIME=local`; dữ liệu thuộc `local-dev`. Không có chế độ chọn người dùng bằng header. MCP bridge chỉ chạy trong chế độ local này.

## Chuyển dữ liệu cũ

Không tự gán dữ liệu không có chủ sở hữu cho người đăng nhập đầu tiên. Dữ liệu cũ vẫn nằm nguyên trong DB và bị ẩn khỏi mọi phiên người dùng. Script dưới đây chỉ chạy offline bằng quyền nền tảng (không chạm tài khoản AWS khách).

1. Sao lưu database/PITR. Hoàn thành hoặc huỷ job và workflow đang chạy; dừng API, agent-worker và executor trước khi chuyển. Script từ chối job active hoặc proposal có task token/đang thi hành.
2. Xác định chính xác Cognito `sub` người nhận (từ User Pool hoặc `/api/auth/me`). Chạy từ `backend/`, dùng cấu hình storage của database muốn chuyển:

   ```bash
   python -m app.storage.migrate_owner --from-user legacy --to-user <Cognito-sub>
   python -m app.storage.migrate_owner --from-user legacy --to-user <Cognito-sub> --apply
   ```

   Dữ liệu đã tạo bằng chế độ dev mới dùng `--from-user local-dev`. Mặc định chỉ kiểm và đếm; `--apply` mới chuyển bản ghi. SQLite thực hiện trong một transaction; DynamoDB kiểm collision toàn bộ trước, rồi chuyển từng item bằng transaction Put+Delete, đổi PK/GSI1PK và owner của tool call nhúng. Nếu bị ngắt, chạy lại để chuyển phần còn lại. Script không in nội dung/credentials.
3. Khởi động lại, kiểm tra bằng người nhận và một tài khoản khác. Không chuyển dữ liệu thật khi chưa xác định chủ sở hữu.

## Kiểm chứng

Test dùng JWT RSA thật, JWKS giả lập, hai người dùng trên SQLite và DynamoDB moto; kiểm token lỗi/hết hạn/sai issuer/client/type/scope, đọc/ghi/xoá chéo, truy cập job và duyệt đề xuất chéo; test callback/refresh/401 ở frontend và resource Cognito/authorizer/payload owner ở CDK. Chưa xác nhận luồng email/Hosted UI và triển khai trên tài khoản AWS thật.

Nguồn thiết kế: [AWS kiểm JWT Cognito](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html), [AWS Code + PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/using-pkce-in-authorization-code.html), [oidc-client-ts](https://authts.github.io/oidc-client-ts/).
