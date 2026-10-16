# AutoAWS — Tổng quan hệ thống

> Tóm tắt từ tài liệu gốc `AutoAWS.docx` (Báo cáo tiến độ, Nhóm 16, ĐH Công nghệ – ĐHQGHN, 10/2026).
> File này tồn tại để người và AI coding agent đọc được nhanh mà không cần mở `.docx`.
> Khi tài liệu gốc thay đổi, cập nhật file này.

## 1. Hệ thống làm gì

**AutoAWS** là trợ lý AI **chẩn đoán và khắc phục sự cố trên môi trường AWS**.

- Người dùng kết nối tài khoản AWS của họ cho hệ thống bằng **quyền chỉ đọc**.
- Người dùng mô tả sự cố bằng ngôn ngữ tự nhiên ("Website báo 502 từ chiều nay").
- Lõi agent dùng LLM để **lập kế hoạch kiểm tra**, gọi **bộ công cụ đọc AWS cố định** lấy dữ liệu thực tế (cấu hình, log, chỉ số, lịch sử thay đổi), **đối chiếu** các nguồn rồi trả lời theo cấu trúc:
  **nguyên nhân → bằng chứng → cách khắc phục từng bước → những điểm chưa xác nhận được**.

Khác với chatbot AI thông thường: câu trả lời gắn với **đúng môi trường của người dùng**, có bằng chứng trích từ dữ liệu đã đọc, không phải khuyến nghị chung chung.

### Hai tính năng

| # | Tính năng | Mô tả | Trạng thái trong plan |
|---|---|---|---|
| 1 | **Chẩn đoán qua hỏi đáp** (chat) | Hỏi tự nhiên → agent tự chọn dữ liệu cần đọc → trả lời có bằng chứng. Hỏi tiếp trong cùng phiên, dữ liệu đã đọc được giữ lại. | **Trọng tâm init** |
| 2 | **Kiểm tra theo checklist** (tuỳ chọn) | Người dùng đưa checklist (mẫu hoặc tự tải lên). Hệ thống chạy từng mục → Đạt / Không đạt / Không đủ dữ liệu, kèm bằng chứng → báo cáo tổng hợp. | Sau init |

## 2. Người dùng

| Nhóm | Đặc điểm | Nhu cầu |
|---|---|---|
| Sinh viên, người mới học AWS | Tự dựng EC2/VPC/DNS lần đầu | Hiểu chính xác lỗi ở đâu, vì sao |
| Lập trình viên, startup nhỏ | Không có DevOps riêng | Khắc phục nhanh khi triển khai/vận hành |
| Kỹ sư DevOps / SysAdmin | Quản lý nhiều tài nguyên, có quy trình | Rút ngắn điều tra; rà soát bằng checklist trước go-live |
| Giảng viên hướng dẫn | Hỗ trợ nhiều sinh viên | Kiểm tra môi trường sinh viên có cấu trúc |

Điểm chung: sở hữu tài khoản AWS, đồng ý cấp quyền **chỉ đọc**, cần câu trả lời gắn với môi trường của mình.

## 3. Quy trình sử dụng

### Giai đoạn A — Kết nối tài khoản AWS (một lần)
1. Đăng ký / đăng nhập ứng dụng web.
2. Ứng dụng cung cấp **mẫu CloudFormation** → người dùng tạo trong tài khoản mình một **IAM role chỉ đọc**, kèm **ExternalId** riêng.
3. Người dùng dán **Role ARN** + chọn **Region**.
4. Hệ thống `AssumeRole` lấy quyền tạm thời, gọi 1 lệnh đọc đơn giản. Thành công → trạng thái **"Đã kết nối"**.

> Bản init hỗ trợ thêm kiểu kết nối **Access Key / Secret Key** để dev/demo nhanh (lệch thiết kế, chỉ dùng dev). Xem `docs/BACKEND_PLAN.md`.

### Giai đoạn B — Chẩn đoán qua hỏi đáp
1. Người dùng mô tả sự cố.
2. Agent lập kế hoạch: cần đọc cấu hình nào, log nào, chỉ số nào, lịch sử thay đổi khoảng nào.
3. Hệ thống nhận quyền tạm thời, gọi API chỉ đọc.
4. Agent đối chiếu, trả lời: nguyên nhân / bằng chứng / khắc phục / chưa xác nhận.
5. Hỏi tiếp trong cùng phiên.

### Giai đoạn C — Checklist (tuỳ chọn, sau init)
Chọn checklist mẫu hoặc tải lên → chạy tuần tự từng mục → lưu kết quả ngay khi xong mục → bảng tổng hợp + khuyến nghị.

## 4. Ba kịch bản minh hoạ (dùng làm test case)

### KB1 — Không SSH được dù Security Group đã mở port 22
- Kiểm tra: instance running + 2/2 status check, public IP → SG cho phép TCP/22 ✔ → **route table của subnet không có tuyến 0.0.0.0/0 → IGW** → CloudTrail: `ReplaceRouteTableAssociation` 2 ngày trước.
- Kết luận: subnet mất đường ra Internet; SG không phải nguyên nhân.
- Khắc phục: gắn lại route table public hoặc thêm tuyến tới IGW. Tạm thời dùng Session Manager (SSM Agent đang chạy).

### KB2 — Đã trỏ tên miền nhưng không vào được app (Docker port 8080)
- Kiểm tra: DNS công khai + Route 53 trỏ `13.212.x.x` → EC2 public IP hiện tại `54.169.x.x` (không khớp) → CloudTrail: instance stop/start hôm qua, IP động đổi → SG chưa mở 8080.
- Kết luận: 2 vấn đề (DNS trỏ IP cũ; SG thiếu 8080).
- Khắc phục: gắn Elastic IP, cập nhật bản ghi A, mở TCP/8080.
- **Chưa xác nhận được từ AWS**: container có chạy/map đúng port không → gợi ý `docker ps`, `ss -tlnp | grep 8080`.

### KB3 — Website 502 sau khi deploy phiên bản mới
- Kiểm tra: CloudWatch metric của LB: 5xx tăng từ 14:05 → target group 2/2 unhealthy, health check `/health` trả 404 → CloudWatch Logs: phiên bản mới đổi health endpoint thành `/api/health` → CloudTrail: deploy lúc 14:03, target group không đổi.
- Kết luận: health check path lệch.
- Khắc phục: đổi health check path của target group hoặc thêm lại route `/health`.

## 5. Phạm vi và giới hạn (ràng buộc cứng cho mọi code)

- **Chỉ đọc.** Không tạo/sửa/xoá tài nguyên. Chỉ dùng API `Describe*`, `List*`, `Get*`, `LookupEvents`, Logs Insights `StartQuery/GetQueryResults`, `GetMetricData`.
- **Không truy cập dữ liệu nghiệp vụ**: không đọc nội dung S3 object, cơ sở dữ liệu, Secrets Manager, Parameter Store, không `kms:Decrypt`.
- **Không truy cập hệ điều hành** của máy chủ. Những gì bên trong máy (container, tiến trình, firewall OS) chỉ biết nếu log đã đẩy lên CloudWatch Logs.
- Khi không xác định được → agent **ghi rõ "chưa xác nhận được từ dữ liệu AWS"** và gợi ý lệnh để người dùng tự kiểm tra, **không đoán**.
- Mọi kết luận **bắt buộc trích dẫn bằng chứng** từ dữ liệu đã đọc.

## 6. Kiến trúc chức năng (7 khối)

```
Người dùng
   │
   ▼
Giao diện web ──► Xác thực (đăng nhập, JWT)
   │  câu hỏi / câu trả lời          checklist
   ▼                                    ▼
Lõi agent  ◄──────────────────  Bộ chạy checklist (từng mục)
 lập kế hoạch → gọi công cụ → phân tích → kết luận
   │ gọi công cụ            │ suy luận          │ lưu
   ▼                        ▼                   ▼
Bộ công cụ đọc AWS     Mô hình ngôn ngữ      Kho lưu trữ
   │ chỉ đọc            (Bedrock / API)      (kết nối, hội thoại, kết quả)
   ▼
Tài khoản AWS của người dùng
   │ dữ liệu thô
   ▼
Bộ lọc dữ liệu nhạy cảm ──► dữ liệu đã làm sạch ──► Lõi agent / Mô hình
```

| Khối | Vai trò | Vào → Ra |
|---|---|---|
| Giao diện web | Chat, kết nối tài khoản, chạy checklist | Thao tác → yêu cầu API; hiển thị kết quả |
| Xác thực | Đăng ký/đăng nhập, cấp token, cách ly dữ liệu từng người | Tài khoản/mật khẩu → JWT |
| Lõi agent | Vòng lặp: lập kế hoạch → gọi công cụ → phân tích → kết luận | Câu hỏi + lịch sử → câu trả lời có bằng chứng |
| Bộ công cụ đọc AWS | Tập hàm đọc **cố định**; model chỉ gọi được các hàm này, không chạy lệnh tuỳ ý | Tên công cụ + tham số → JSON |
| Bộ lọc dữ liệu nhạy cảm | Rút gọn, che email/token/khoá trước khi đưa vào model | Dữ liệu thô → đã làm sạch |
| Bộ chạy checklist | Tách mục, chạy tuần tự, mỗi mục gọi lõi agent | Danh sách mục → kết quả từng mục + báo cáo |
| Kho lưu trữ | Lưu kết nối, hội thoại, kết quả checklist | Bản ghi → bản ghi |

### 7 nhóm công cụ đọc AWS

| Nhóm | Nguồn | Câu hỏi trả lời được |
|---|---|---|
| Máy chủ | EC2, SSM | Instance có chạy không, IP nào, SSM Agent có hoạt động không |
| Mạng | Security Group, NACL, route table, Internet Gateway | Kết nối bị chặn ở lớp nào |
| DNS | Route 53, truy vấn DNS công khai | Tên miền trỏ về đâu, có khớp IP thực tế không |
| Load Balancer | ELB, target group | Target có healthy không, vì sao không |
| Chỉ số giám sát | CloudWatch Metrics | Sự cố bắt đầu khi nào, mức độ ra sao |
| Log | CloudWatch Logs (Logs Insights) | Ứng dụng báo lỗi gì trong khoảng thời gian sự cố |
| Lịch sử thay đổi | CloudTrail | Ai đã thay đổi gì, vào lúc nào |

### Tri thức chẩn đoán

Agent được nạp sẵn **thứ tự kiểm tra theo đường đi của một kết nối**:

`DNS → địa chỉ IP → route table → Network ACL → Security Group → Load Balancer → instance → ứng dụng`

Nhờ vậy agent kiểm tra có thứ tự thay vì liệt kê nguyên nhân chung chung.

## 7. Kiến trúc triển khai đích (serverless, 2 tài khoản)

> Đây là đích cuối. **Bản init chạy local** (FastAPI + React) nhưng cấu trúc code bám theo các khối này để sau đóng gói lên Lambda.

**Tài khoản nền tảng AutoAWS** chứa toàn bộ ứng dụng; **tài khoản người dùng** chỉ được truy cập qua IAM role chỉ đọc + STS credentials tạm thời (~15 phút).

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Giao diện | React, S3 + CloudFront | Phân phối giao diện qua HTTPS |
| Xác thực | Amazon Cognito | Đăng ký/đăng nhập, JWT (OIDC, Authorization Code + PKCE) |
| Cổng API | API Gateway (HTTP API) | Cổng vào duy nhất, JWT authorizer |
| Xử lý | Lambda (Python): `api-handler`, `agent-worker` | Xử lý yêu cầu; chạy vòng lặp agent (bất đồng bộ) |
| Điều phối checklist | Step Functions | Chạy từng mục, giữ trạng thái, retry |
| Mô hình AI | Bedrock (Claude, tool use) + Guardrails | Lập luận, chọn công cụ; che dữ liệu nhạy cảm |
| Truy cập chéo tài khoản | IAM + STS | `AssumeRole` kèm ExternalId, chỉ đọc |
| Lưu trữ | DynamoDB + KMS | Kết nối, hội thoại, kết quả; mã hoá |
| Giám sát | CloudWatch, X-Ray, CloudTrail | Log, metric, cảnh báo, kiểm toán |
| Hạ tầng | AWS CDK, GitHub Actions | IaC, CI/CD |

Giao diện I1–I16 (tóm tắt): I1 CloudFront/S3 · I2 Cognito OIDC · I3 API GW + JWT · I4 Lambda proxy · I5 gọi agent-worker async · I6 StartExecution Step Functions · I7 từng mục checklist · I8 Bedrock Converse · I9 STS AssumeRole + ExternalId · I10 API cấu hình (SigV4) · I11 DynamoDB · I12 CloudWatch nền tảng · I13 CloudTrail (cả 2 tài khoản) · I14 DNS công khai · I15 Logs Insights + GetMetricData · I16 CloudTrail LookupEvents (90 ngày).

### Bảo mật truy cập tài khoản người dùng
- **ExternalId riêng từng người dùng** (chặn dán ARN role của người khác).
- **Quyền tối thiểu**: chỉ Describe/List/Get + log/metric/CloudTrail; **deny rõ ràng** S3 object, Secrets Manager, Parameter Store, KMS Decrypt.
- **Credentials tạm thời**: chỉ trong bộ nhớ, không ghi log/DB.
- Log chỉ truy vấn trong khoảng thời gian liên quan; che nhạy cảm trước khi gửi model; không lưu lâu.
- Mọi lệnh đọc đều hiện trong CloudTrail của người dùng → họ kiểm tra lại được.

## 8. Kế hoạch, mốc, phân công (từ tài liệu)

**Thành viên:** TV1 Trần Phúc Khánh · TV2 Phạm Phúc Bình · TV3 Dương Đình Minh (nhóm trưởng) · TV4 Lê Minh Đạt.

| Hạng mục | Phụ trách |
|---|---|
| Chốt phạm vi; thiết kế IAM; hạ tầng CDK; API Gateway + api-handler; giám sát/CI/CD; kiểm thử; bảo mật & chi phí; tài liệu | TV3 |
| Công cụ đọc cấu hình (máy chủ, mạng, DNS, LB); công cụ đọc log/chỉ số/CloudTrail | TV2 |
| Lõi agent với Bedrock; tri thức chẩn đoán & bộ lọc dữ liệu | TV1 |
| Bộ chạy checklist; giao diện web | TV4 |

| Mốc | Thời điểm | Tiêu chí |
|---|---|---|
| M1 — Kết nối được tài khoản | Cuối tuần 2 | Tạo role bằng CloudFormation, kết nối thành công, "Đã kết nối" |
| M2 — Chẩn đoán cấu hình | Cuối tuần 4 | Đúng KB1, KB2 trên môi trường mẫu, có bằng chứng + cách sửa |
| M3 — Chẩn đoán qua log, checklist | Cuối tuần 6 | Đúng KB3 (log + chỉ số + CloudTrail); checklist chạy end-to-end |
| M4 — Demo & báo cáo | Cuối tuần 8 | Đạt kiểm thử, rà soát bảo mật, demo |

**Rủi ro đáng nhớ:** Bedrock chưa bật/quota → có thể tạm gọi model qua API ngoài (lý do bản init để LLM provider pluggable). Log quá lớn → chỉ truy vấn quanh thời điểm sự cố, lọc theo mức lỗi, tóm tắt. Model đoán mò → ép đầu ra có trường "chưa xác nhận được". Chi phí → giới hạn số vòng agent, cache kết quả.
