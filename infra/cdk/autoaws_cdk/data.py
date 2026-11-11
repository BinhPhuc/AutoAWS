"""AutoAws-Data: the single DynamoDB table (backend app/storage/dynamo.py) + its KMS key."""

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_kms as kms
from constructs import Construct

from .config import Config


class DataStack(Stack):
    def __init__(self, scope: Construct, cid: str, cfg: Config, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)
        removal = RemovalPolicy.DESTROY if cfg.destroy_data else RemovalPolicy.RETAIN

        # Customer managed key: every use is recorded in CloudTrail (report §2.3.1)
        self.key = kms.Key(
            self,
            "TableKey",
            alias=f"alias/autoaws-{cfg.env_name}-table",
            enable_key_rotation=True,
            removal_policy=removal,
        )
        self.table = ddb.TableV2(
            self,
            "Table",
            table_name=cfg.table_name,
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing=ddb.Billing.on_demand(),
            encryption=ddb.TableEncryptionV2.customer_managed_key(self.key),
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            time_to_live_attribute="ttl",  # jobs expire after JOB_TTL_DAYS
            removal_policy=removal,
            global_secondary_indexes=[
                ddb.GlobalSecondaryIndexPropsV2(
                    index_name="GSI1",
                    partition_key=ddb.Attribute(name="GSI1PK", type=ddb.AttributeType.STRING),
                    sort_key=ddb.Attribute(name="GSI1SK", type=ddb.AttributeType.STRING),
                ),
                ddb.GlobalSecondaryIndexPropsV2(
                    index_name="ById",
                    partition_key=ddb.Attribute(name="id", type=ddb.AttributeType.STRING),
                ),
            ],
        )
