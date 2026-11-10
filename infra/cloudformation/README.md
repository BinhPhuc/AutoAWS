# DynamoDB cho backend EC2

Đăng nhập Cognito cho cùng mô hình triển khai: dùng [`cognito.yaml`](cognito.yaml)
và hướng dẫn [`COGNITO.md`](COGNITO.md) (Hosted UI + PKCE, Outputs cho backend).

Template `dynamodb.yaml` tạo một bảng trong **tài khoản nền tảng AutoAWS**, dùng đúng
schema của `backend/app/storage/dynamo.py`: khoá `PK`/`SK`, hai GSI `GSI1` và `ById`
(projection `ALL`), TTL trên thuộc tính `ttl`, trả phí theo yêu cầu và mã hoá KMS
bằng AWS managed key `aws/dynamodb`. Không tạo EC2, IAM role hay frontend.

## 1. Tạo bảng

Trong AWS Console, chọn region muốn dùng → CloudFormation → Create stack → Upload
template file → chọn `infra/cloudformation/dynamodb.yaml`.

- Đặt stack name, ví dụ `autoaws-data`.
- `TableName`: tên bảng bạn muốn tạo (mặc định `autoaws`). Không dùng tên bảng đã tồn tại.
- `EnablePointInTimeRecovery`: mặc định `false` để giảm chi phí demo; chọn `true` nếu
  cần bản sao lưu liên tục.
- Tạo stack và chờ `CREATE_COMPLETE` trước khi chạy backend.

Trong Outputs có `TableName`, `TableArn`, `Region`, `EndpointUrl`. Bảng dùng
`DeletionPolicy: Retain` và `UpdateReplacePolicy: Retain`: xoá stack vẫn giữ bảng;
nếu cần dọn demo hoàn toàn, bạn tự xoá bảng sau. Template không thay đổi stack CDK.

## 2. Điền cấu hình backend

Tạo `backend/.env` từ `backend/.env.example` nếu chưa có, rồi tự điền:

```dotenv
STORAGE_BACKEND=dynamodb
DYNAMODB_TABLE=your-table-name
DYNAMODB_REGION=ap-southeast-1
DYNAMODB_ENDPOINT_URL=
DYNAMODB_CREATE_TABLE=false
PLATFORM_AWS_PROFILE=
```

Tên bảng và region phải khớp Outputs của stack. Với AWS thật, có thể để trống
`DYNAMODB_ENDPOINT_URL` để boto3 tự chọn endpoint theo region, hoặc điền `EndpointUrl`
từ Outputs. Không điền ARN bảng vào endpoint URL. Không đặt `AWS_ENDPOINT_URL` thành
endpoint DynamoDB: biến đó dành riêng cho tool AWS khi dùng môi trường giả lập.
`DYNAMODB_KMS_KEY_ID` chỉ dùng khi app tự tạo bảng ở chế độ dev, không cần điền cho stack này.

Backend mặc định dùng DynamoDB, không tự tạo bảng và không tự chuyển sang SQLite.
Khi khởi động, backend kiểm tra tên bảng và gọi `DescribeTable`; thiếu bảng, credentials
hoặc quyền truy cập sẽ làm khởi động thất bại. Không cần `DB_PATH` hay volume SQLite.
Dữ liệu SQLite cũ không tự được nhập vào DynamoDB.

## 3. Quyền truy cập của backend

Backend dùng credentials **nền tảng**, qua boto3 default credential chain hoặc
`PLATFORM_AWS_PROFILE`, tách biệt credentials tài khoản người dùng trong Connections.
Trên EC2 nên dùng instance IAM role và để trống `PLATFORM_AWS_PROFILE`.

Gắn quyền sau vào role nền tảng đang dùng cho EC2; thay `REGION`, `ACCOUNT_ID`,
`TABLE_NAME` bằng giá trị thực. ARN bảng lấy từ Output `TableArn`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeTable",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/TABLE_NAME",
        "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/TABLE_NAME/index/*"
      ]
    }
  ]
}
```

Không cần `CreateTable`, `UpdateTable`, `DeleteTable`, `UpdateTimeToLive` trong role
runtime vì CloudFormation quản lý bảng. Các quyền Bedrock và `sts:AssumeRole` hiện có
của backend vẫn cần cấu hình theo chức năng sử dụng.

Container phải truy cập được EC2 instance metadata để lấy credentials của role.
Nếu dùng IMDSv2 qua Docker bridge, cấu hình metadata response hop limit phù hợp
(thường là `2`); hop limit `1` có thể khiến container không lấy được credentials.

## 4. Chạy trên EC2

Từ thư mục gốc repo:

```bash
docker compose -f docker-compose.backend.yml up -d --build
docker compose -f docker-compose.backend.yml logs -f backend
curl http://localhost:8000/api/health
```

Compose buộc `STORAGE_BACKEND=dynamodb` và `DYNAMODB_CREATE_TABLE=false`; table,
region và endpoint lấy từ `backend/.env`. Healthcheck chỉ kiểm tra API còn phản hồi;
để kiểm tra ghi/đọc dữ liệu, tạo một Connection trong UI rồi tải lại danh sách.

## Tham khảo

- [AWS::DynamoDB::Table](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-dynamodb-table.html)
- [Mã hoá SSE của DynamoDB trong CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-dynamodb-table-ssespecification.html)
- [Quyền truy cập bảng và index](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/iam-policy-specific-table-indexes.html)
- [EC2 instance metadata options](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-options.html)
