# Bộ câu hỏi 7 kịch bản kiểm thử (KB1–KB7)

Tài liệu này dùng khi **demo** và khi **chấm chẩn đoán**. Mỗi kịch bản gồm:
- hệ thống đang chạy và lỗi được cài;
- câu hỏi người dùng gõ vào AutoAWS;
- câu trả lời mong nhận được: nguyên nhân, bằng chứng, cách khắc phục và hành động AutoAWS nên đề xuất.

Bảy kịch bản khớp Bảng 2.14 của báo cáo tiến độ lần 2.

## Chạy và chấm thế nào

1. Dựng và cài lỗi trên tài khoản AWS test. Chi tiết, chi phí và các lưu ý xem `infra/aws-scenarios/README.md`.
   ```bash
   PY=backend/.venv/bin/python; S=infra/aws-scenarios/scenario.py
   $PY $S up kb1 --profile <test-profile> --region <region>
   $PY $S fault kb1 --profile <test-profile> --region <region>   # KB5, KB6 không cần bước này
   ```
2. **Đợi 5–15 phút** để CloudTrail ghi kịp sự kiện `fault`. Riêng KB3 cần thêm 1–3 phút để alarm chuyển trạng thái.
3. Tạo kết nối trong AutoAWS **đúng region** của kịch bản, rồi hỏi đúng câu trong mục "Câu hỏi".
4. Đối chiếu câu trả lời với mục "Câu trả lời mong muốn" theo Bảng 2.15:
   - đúng nguyên nhân;
   - bằng chứng là dữ liệu đọc được, không phải suy đoán;
   - cách sửa đúng;
   - không bịa thêm thông tin.

   Chấm tự động bằng `infra/eval/run_eval.py --answers infra/aws-scenarios/answers.aws.json`. File này do `scenario.py` ghi, chứa ID tài nguyên thật và các từ khoá phải xuất hiện, được trích ở dòng "Từ khoá chấm" của từng kịch bản.
5. Test xong thì chạy `$PY $S down kb1 ...` để xoá stack. Nếu đã áp dụng bản sửa có cấp Elastic IP thì kiểm tra lại Elastic IP còn sót.

Trong tài liệu, ID ở dạng `<...>` thay đổi theo mỗi lần dựng. ID thật nằm trong `scenario.py status kbN` và `answers.aws.json`.

| KB | Lớp lỗi | Câu hỏi (tóm tắt) | Nguyên nhân | AutoAWS đề xuất sửa |
|---|---|---|---|---|
| KB1 | Định tuyến | Không SSH được, SG đã mở 22 | Subnet gắn route table không có `0.0.0.0/0 → igw` | `associate_route_table` |
| KB2 | DNS + Security Group | Trỏ tên miền về EC2 mà không vào được app 8080 | Bản ghi A trỏ IP cũ; SG chưa mở 8080 | `upsert_a_record`, `authorize_sg_ingress` |
| KB3 | Load balancer | Alarm UnHealthyHostCount, web vẫn chạy | Health check `/health`, bản mới chỉ có `/api/health` | `modify_health_check_path` |
| KB4 | Network ACL | SSH treo rồi timeout | NACL chặn cổng tạm 1024–65535 chiều ra | — (hướng dẫn sửa tay) |
| KB5 | Địa chỉ IP | Instance mới không SSH được | Instance không có public IP | `allocate_and_associate_eip` |
| KB6 | Security Group | Ở công ty SSH được, về nhà thì không | SG chỉ mở 22 cho IP công ty cũ | `authorize_sg_ingress` (IP nhà /32) |
| KB7 | Ứng dụng / log | Sau deploy, API trả 500 cho mọi request | Bản v2.5.0 không kết nối được DB `10.70.9.15:5432` | — (rollback ứng dụng / sửa cấu hình DB) |

---

## KB1 — Subnet mất đường ra Internet

**Hệ thống**
- VPC `10.10.0.0/16` có một public subnet chứa instance `web-server` (có public IP).
- Security Group mở port 22.
- Route table public có `0.0.0.0/0 → igw-<...>`.
- Trong VPC còn một route table thứ hai chỉ có route `local`.

**Lỗi được cài** (`fault kb1`): gọi `ReplaceRouteTableAssociation` để chuyển subnet của `web-server` sang route table thứ hai. Từ lúc đó subnet không còn đường ra Internet.

**Câu hỏi**
> Tôi không SSH được vào instance web-server, Security Group đã mở port 22 rồi.

**Câu trả lời mong muốn**
- **Nguyên nhân:** subnet `subnet-<...>` của `web-server` đang gắn route table `rtb-<private>`. Route table này không có route `0.0.0.0/0` tới Internet Gateway, nên gói trả lời SSH không ra được Internet.
- **Bằng chứng:**
  - `describe_route_tables`: route table của subnet chỉ có `10.10.0.0/16 → local`;
  - Security Group đúng là có mở 22 nên không phải nguyên nhân, instance vẫn có public IP;
  - CloudTrail có sự kiện `ReplaceRouteTableAssociation`, cho biết ai đổi và lúc nào.
- **Cách khắc phục:** gắn subnet lại route table public `rtb-<public>` (đang có `0.0.0.0/0 → igw`), hoặc thêm route `0.0.0.0/0 → igw-<...>` vào route table hiện tại.
- **AutoAWS đề xuất:** `associate_route_table` (subnet → `rtb-<public>`), sau đó kiểm chứng route table mới của subnet. Ngoài ra có thể dùng `create_route_to_igw`.

**Từ khoá chấm:** `rtb-<private>` hoặc "route table"; và `0.0.0.0/0` / "igw" / "internet gateway".

---

## KB2 — Tên miền trỏ IP cũ và Security Group chưa mở 8080

Cần một tên miền đã có public hosted zone trên Route 53.

**Hệ thống**
- Instance `app-server` chạy một ứng dụng Docker ở port 8080.
- Bản ghi `app.<domain>` kiểu A trỏ public IP của instance.
- Lỗi có sẵn từ lúc dựng: Security Group **không** mở port 8080.

**Lỗi được cài** (`fault kb2`): stop rồi start instance. Public IP tự gán bị đổi, nhưng bản ghi A vẫn trỏ IP cũ.

**Câu hỏi**
> Tôi chạy ứng dụng Docker ở port 8080, đã trỏ app.\<domain\> về EC2 nhưng không vào được.

**Câu trả lời mong muốn** (có **hai** nguyên nhân, phải nêu đủ):
1. **Bản ghi DNS trỏ sai IP.**
   - Nguyên nhân: `app.<domain>` A đang là `<IP cũ>`, trong khi instance hiện có public IP `<IP mới>`.
   - Bằng chứng: `route53_list_records` đối chiếu với `describe_instances`; phân giải DNS ra IP cũ; CloudTrail có `StopInstances` và `StartInstances`.
   - Khắc phục: cập nhật bản ghi A sang `<IP mới>`. Để IP không đổi nữa thì gắn Elastic IP cho instance.
2. **Security Group chưa mở 8080.**
   - Nguyên nhân: SG `sg-<...>` chỉ mở 22, 80 và 443, không có 8080.
   - Bằng chứng: `describe_security_groups`.
   - Khắc phục: thêm inbound TCP 8080 từ nguồn cần truy cập.
- **AutoAWS đề xuất:** `upsert_a_record` (A `app.<domain>` → `<IP mới>`) và `authorize_sg_ingress` (TCP 8080).
- **Điểm chưa xác nhận:** container có thật sự lắng nghe 8080 hay không. Agent không đọc được nội dung bên trong instance, nên phải ghi là chưa xác nhận và đưa lệnh để người dùng tự kiểm tra, ví dụ `docker ps`, `curl localhost:8080`.

**Từ khoá chấm:** `<IP cũ>`; và `8080` cùng `sg-<...>` / "security group".

---

## KB3 — Health check sai đường dẫn sau khi deploy

**Hệ thống**
- Application Load Balancer đứng trước 2 instance ở 2 AZ, chạy web v1.4.2.
- Target group `autoaws-kb3-tg` kiểm tra sức khoẻ ở `/health`.
- Alarm CloudWatch đặt trên `UnHealthyHostCount`.
- Log ứng dụng đẩy về `/demo/kb3-web`.

**Lỗi được cài** (`fault kb3`): "deploy" bản v2.0.0 qua SSM Run Command.
- Bản v2 đổi health endpoint thành `/api/health`, còn `/health` trả 404.
- Vì vậy cả 2 target thành unhealthy.
- Khi mọi target đều unhealthy, ALB vẫn chuyển request tới chúng (fail-open), nên website vẫn vào được.

**Câu hỏi**
> Từ chiều nay CloudWatch liên tục cảnh báo UnHealthyHostCount, cả 2 target đều unhealthy dù website vẫn vào được. Chuyện gì đang xảy ra?

**Câu trả lời mong muốn**
- **Nguyên nhân:** target group vẫn kiểm tra `/health`, nhưng bản v2.0.0 vừa deploy chỉ phục vụ `/api/health`. Health check nhận 404, nên 2/2 target bị đánh dấu unhealthy.
- **Bằng chứng:**
  - `describe_target_health`: 2/2 target unhealthy, lý do `Target.ResponseCodeMismatch` (404);
  - `describe_target_groups`: `HealthCheckPath=/health`;
  - alarm `UnHealthyHostCount` ở trạng thái ALARM, metric tăng lên 2;
  - log `/demo/kb3-web` ghi `GET /health 404 (v2.0.0)`;
  - CloudTrail có `SendCommand` (SSM), trùng thời điểm bắt đầu lỗi.
- **Vì sao web vẫn chạy:** khi không còn target nào healthy, ALB fail-open và vẫn chuyển request tới mọi target.
- **Cách khắc phục:** đổi health check path của target group sang `/api/health`, hoặc rollback ứng dụng về v1.
- **AutoAWS đề xuất:** `modify_health_check_path` → `/api/health`, rồi kiểm chứng bằng cách đợi target healthy trở lại.
  - Nếu agent chưa tìm thấy đường dẫn mới trong log, nó phải hỏi lại hoặc ghi là chưa xác nhận, không được đoán.
  - Người dùng có thể nói thêm "bản mới dùng /api/health" để agent đề xuất.

**Từ khoá chấm:** `/health`; và `/api/health` / "health check" / "unhealthy".

---

## KB4 — Network ACL chặn cổng tạm chiều ra

**Hệ thống**
- Instance `api-server`, Security Group mở 22 cho mọi nơi.
- Trong VPC có một Network ACL tự tạo, **chặn outbound TCP 1024–65535**. NACL này lúc đầu chưa gắn vào subnet nào.

**Lỗi được cài** (`fault kb4`): gọi `ReplaceNetworkAclAssociation` để gắn NACL đó vào subnet của `api-server`.
- NACL là stateless: gói SYN vào port 22 vẫn qua được.
- Nhưng gói trả lời đi ra bằng cổng tạm (1024–65535) bị chặn, nên SSH treo rồi timeout.

**Câu hỏi**
> SSH vào api-server bị treo rồi timeout, Security Group đã cho phép port 22 từ mọi nơi.

**Câu trả lời mong muốn**
- **Nguyên nhân:** subnet của `api-server` đang dùng Network ACL `acl-<...>`. NACL này có rule outbound DENY TCP 1024–65535. Vì NACL không nhớ trạng thái kết nối, gói trả lời SSH (cổng tạm của client) bị chặn khi đi ra.
- **Bằng chứng:**
  - `describe_network_acls`: rule outbound deny 1024–65535 và subnet đang được gắn NACL này;
  - Security Group và route table đều đúng;
  - CloudTrail có `ReplaceNetworkAclAssociation`.
- **Cách khắc phục:** gắn subnet lại NACL mặc định của VPC, hoặc thêm rule outbound ALLOW TCP 1024–65535 với số rule nhỏ hơn rule deny.
- **AutoAWS:** danh mục khắc phục chưa có hành động NACL, nên chỉ hướng dẫn sửa tay, kèm lệnh CLI cụ thể. Không có đề xuất chờ duyệt.

**Từ khoá chấm:** `acl-<...>` / "network acl" / "nacl"; và `1024` / "ephemeral" / "cổng tạm" / "outbound".

---

## KB5 — Instance không có public IP

**Hệ thống**
- Instance `worker-01` nằm trong một subnet có route `0.0.0.0/0 → igw` bình thường.
- Subnet này **không tự gán public IP** (`MapPublicIpOnLaunch=false`), nên instance chỉ có IP private.

**Lỗi:** có sẵn từ lúc dựng, không cần bước `fault`.

**Câu hỏi**
> Tôi vừa tạo instance worker-01 nhưng không SSH vào được.

**Câu trả lời mong muốn**
- **Nguyên nhân:** `worker-01` (`i-<...>`) không có public IP, vì subnet `subnet-<...>` không tự gán public IP khi tạo instance. Từ Internet không có địa chỉ nào để SSH tới.
- **Bằng chứng:**
  - `describe_instances`: không có `PublicIpAddress`;
  - `describe_subnets`: `MapPublicIpOnLaunch=false`;
  - route table có `0.0.0.0/0 → igw` và Security Group mở 22, tức các lớp này đều ổn.
- **Cách khắc phục:** cấp một Elastic IP rồi gắn vào instance. Về lâu dài, bật auto-assign public IP cho subnet hoặc đi qua bastion / SSM Session Manager.
- **AutoAWS đề xuất:** `allocate_and_associate_eip` cho `i-<...>`. Hoàn tác (Undo change) sẽ gỡ và trả lại Elastic IP.

**Từ khoá chấm:** "public ip" / "ip public" / "ip công khai" / "elastic ip".

---

## KB6 — Security Group chỉ mở SSH cho IP công ty cũ

**Hệ thống**
- Instance `bastion`, Security Group chỉ cho SSH (22) từ `203.0.113.10/32`. Đây là IP công ty cũ của người dùng.

**Lỗi:** có sẵn từ lúc dựng, không cần bước `fault`.

**Câu hỏi**
> Ở công ty tôi SSH vào bastion được, nhưng về nhà thì không vào được.

**Câu trả lời mong muốn**
- **Nguyên nhân:** Security Group `sg-<...>` của `bastion` chỉ cho SSH từ `203.0.113.10/32`. IP mạng nhà khác IP này, nên kết nối bị chặn.
- **Bằng chứng:**
  - `describe_security_groups`: rule inbound 22 duy nhất có nguồn `203.0.113.10/32`;
  - instance có public IP, route table và NACL đều ổn.
- **Cách khắc phục:** thêm rule inbound 22 cho **đúng IP nhà dạng /32**. Người dùng xem IP nhà bằng `curl https://checkip.amazonaws.com`. Cách khác là dùng VPN công ty hoặc SSM Session Manager.
- **Không được** đề xuất mở 22 cho `0.0.0.0/0` (ràng buộc cứng #1).
- **AutoAWS đề xuất:** `authorize_sg_ingress` (TCP 22, `<IP nhà>/32`).
  - Agent không biết IP nhà, nên phải hỏi lại hoặc để người dùng nói thêm, ví dụ "IP nhà tôi là x.x.x.x". Không được tự điền một IP.
  - Người dùng cũng có thể sửa tham số đề xuất trước khi duyệt.

**Từ khoá chấm:** `203.0.113.10`.

---

## KB7 — Bản deploy mới không kết nối được database

**Hệ thống**
- Instance chạy `orders-api` v2.4.3, mọi request trả 200.
- Log ứng dụng đẩy về CloudWatch Logs `/demo/kb7-orders-api`.

**Lỗi được cài** (`fault kb7`): "deploy" bản v2.5.0 qua SSM Run Command.
- Bản v2.5.0 kết nối database `10.70.9.15:5432`, một địa chỉ trong VPC không có gì lắng nghe.
- Mỗi request `/api/*` bị timeout, trả 500, và log ghi traceback `OperationalError`.

**Câu hỏi**
> Từ sau khi deploy bản mới, orders-api trả lỗi 500 cho mọi request. Log ứng dụng đẩy lên CloudWatch Logs.

**Câu trả lời mong muốn**
- **Nguyên nhân:** từ bản v2.5.0, ứng dụng không kết nối được database `10.70.9.15:5432` (timeout), nên mọi request API trả 500. Hạ tầng mạng của instance không phải nguyên nhân.
- **Bằng chứng:**
  - truy vấn Logs Insights trên `/demo/kb7-orders-api`: traceback `OperationalError` với nội dung kết nối `10.70.9.15:5432` bị timeout, xuất hiện từ lúc chuyển sang 2.5.0;
  - trước đó, bản 2.4.3 trả 200;
  - CloudTrail có `SendCommand` (SSM) đúng thời điểm deploy.
- **Cách khắc phục:**
  - rollback về v2.4.3;
  - hoặc sửa cấu hình DB của bản mới (`DB_HOST` / `DB_PORT`) cho đúng máy chủ database;
  - nếu database thật sự ở `10.70.9.15`, kiểm tra nó có đang chạy không và Security Group của nó có mở 5432 cho instance không.
- **AutoAWS:** danh mục khắc phục không có hành động cho lỗi tầng ứng dụng, nên chỉ hướng dẫn. Không có đề xuất chờ duyệt.
- **Điểm chưa xác nhận:** database đúng ra phải ở đâu. Agent chỉ thấy địa chỉ trong log, nên ghi là chưa xác nhận.

**Từ khoá chấm:** `5432` / "orders-db" / "operationalerror" / "database" / "cơ sở dữ liệu".

---

## Câu hỏi phụ nên thử khi demo

- **Hỏi lại sau khi sửa** (ví dụ KB1, sau khi duyệt đề xuất): "Giờ SSH được chưa?" Agent phải đọc lại cấu hình, không trả lời theo trí nhớ. Có thể bấm `refresh` để bỏ cache.
- **Lời chào hoặc cảm ơn:** "cảm ơn" chỉ được trả lời ngắn và không gọi AWS.
- **Ngoài phạm vi:** hỏi nội dung một S3 object hoặc secret. Agent phải từ chối, vì nó không có tool đọc dữ liệu nghiệp vụ.
