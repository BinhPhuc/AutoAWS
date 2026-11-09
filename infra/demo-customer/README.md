# demo-customer — môi trường AWS giả lập "tài khoản người dùng"

Dùng để dựng hạ tầng có lỗi cài sẵn (KB1–KB3) cho agent chẩn đoán. Triển khai vào **tài khoản Khách**, không phải tài khoản nền tảng.

## network.yaml (việc 11)

| Tài nguyên | Giá trị |
|---|---|
| VPC | `10.20.0.0/16`, bật DNS hostnames |
| Public subnet A / B | `10.20.1.0/24` / `10.20.2.0/24`, 2 AZ khác nhau, tự gán public IP |
| Internet Gateway | gắn vào VPC |
| `demo-public-rt` | `0.0.0.0/0 → IGW`, gắn cả 2 subnet |
| `demo-isolated-rt` | chỉ tuyến local, chưa gắn subnet — dành cho KB1 |

Mọi tài nguyên có tag `Project=autoaws-demo` (truyền qua `--tags` khi deploy). Tất cả **miễn phí**.

## Chạy (Git Bash / Linux / macOS)

```bash
./infra/demo-customer/up.sh      # tạo hoặc cập nhật, in Outputs
./infra/demo-customer/down.sh    # xoá (xoá stack EC2/ALB của việc 13–15 trước)
```
Mặc định profile `autoaws-customer`, region `ap-southeast-1`; đổi bằng `AWS_PROFILE=... AWS_REGION=...`.

## Outputs dùng cho việc sau

- `PublicSubnetA`, `PublicSubnetB`, `VpcId` → EC2/ALB của KB1–KB3.
- `PublicSubnetARouteTableAssociation`, `IsolatedRouteTable` → KB1:
  `aws ec2 replace-route-table-association --association-id <assoc> --route-table-id <isolated-rt>`.
  Khôi phục: chạy lại lệnh với `PublicRouteTable` (association id mới lấy bằng `describe-route-tables`).

> KB1 làm subnet A mất Internet, nên ALB của KB3 (dùng A và B) cũng bị ảnh hưởng — không bật KB1 và KB3 cùng lúc.

## readonly-role.yaml (việc 12)

Role `AutoAWSReadOnly`: trust tài khoản nền tảng + `sts:ExternalId`; Allow đúng các action mà tool cần, Deny dữ liệu nghiệp vụ.
File **sinh tự động** từ `backend/app/aws/cloudformation.py` — không sửa tay; khi thêm tool thì sinh lại:

```bash
cd backend && python -c "from app.aws.cloudformation import render_template; open('../infra/demo-customer/readonly-role.yaml','w',newline='\n').write(render_template('', ''))"
```

Deploy (cần quyền IAM — user admin):

```bash
python -c "import secrets; print('autoaws-' + secrets.token_hex(12))"   # tạo ExternalId
PLATFORM_ACCOUNT_ID=<12 số> EXTERNAL_ID=<autoaws-...> ./infra/demo-customer/role-up.sh   # in ra Role ARN
```

Không commit Account ID / ExternalId thật; gửi Role ARN + ExternalId cho phía nền tảng qua kênh riêng.
Thu hồi quyền: `aws cloudformation delete-stack --stack-name AutoAWSReadOnlyRole`.
