"""AutoAws-Agent: Lambda agent-worker and action-executor with their IAM roles (report
Table 2.10). agent-worker is the only component that talks to the LLM and it can never
assume the remediation role; action-executor is the only one that can."""

from aws_cdk import ArnFormat, Duration, Stack
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from .config import AGENT_ROLE_NAME, EXECUTOR_ROLE_NAME, STATE_MACHINE_NAME, Config

READ_ONLY_ROLE = "AutoAWSReadOnly"  # customer roles (backend app/aws/cloudformation.py)
REMEDIATION_ROLE = "AutoAWSRemediation"


def log_group(scope: Construct, cid: str) -> logs.LogGroup:
    return logs.LogGroup(scope, cid, retention=logs.RetentionDays.ONE_MONTH)


def code(cfg: Config) -> lambda_.Code:
    return lambda_.Code.from_asset(str(cfg.lambda_asset))


def common_env(stack: Stack, cfg: Config, table: ddb.ITableV2, site_url: str) -> dict[str, str]:
    """Backend settings (app/config.py) shared by every function. ``site_url``: the web app
    (links in notification emails)."""
    return {
        "APP_ENV": cfg.env_name,
        "RUNTIME": "lambda",
        "STORAGE_BACKEND": "dynamodb",
        "DYNAMODB_TABLE": table.table_name,
        "DYNAMODB_REGION": stack.region,
        "DYNAMODB_CREATE_TABLE": "false",  # the table belongs to AutoAws-Data
        "REMEDIATION_STATE_MACHINE_ARN": state_machine_arn(stack),
        "PLATFORM_AWS_ACCOUNT_ID": stack.account,
        "PLATFORM_AGENT_ROLE_ARN": f"arn:aws:iam::{stack.account}:role/{AGENT_ROLE_NAME}",
        "PLATFORM_EXECUTOR_ROLE_ARN": f"arn:aws:iam::{stack.account}:role/{EXECUTOR_ROLE_NAME}",
        "FRONTEND_URL": site_url,
    }


def state_machine_arn(stack: Stack) -> str:
    # Built from the fixed name (no token): avoids a dependency cycle Agent <-> Workflow.
    return stack.format_arn(
        service="states",
        resource="stateMachine",
        resource_name=STATE_MACHINE_NAME,
        arn_format=ArnFormat.COLON_RESOURCE_NAME,
    )


class AgentStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        cfg: Config,
        table: ddb.ITableV2,
        key: kms.IKey,
        site_url: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        env = common_env(self, cfg, table, site_url)
        sm_arn = state_machine_arn(self)

        # ---- agent-worker: LLM + read-only role ----------------------------------------
        agent_role = iam.Role(
            self,
            "AgentWorkerRole",
            role_name=AGENT_ROLE_NAME,
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess"),
            ],
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadUserAccountsReadOnly",
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::*:role/{READ_ONLY_ROLE}"],
            )
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                sid="ClaudeOnBedrock",  # Mantle endpoint (anthropic SDK client)
                actions=["bedrock-mantle:CreateInference", "bedrock-mantle:CountTokens"],
                resources=[f"arn:aws:bedrock-mantle:{self.region}:{self.account}:project/*"],
                conditions={
                    "StringEquals": {
                        "bedrock-mantle:Model": [cfg.bedrock_model_id, cfg.bedrock_fallback_model]
                    }
                },
            )
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                sid="StartRemediationFlow", actions=["states:StartExecution"], resources=[sm_arn]
            )
        )
        agent_role.add_to_policy(
            iam.PolicyStatement(
                sid="ResumeRemediationFlow",  # lazy expiry from a background step
                actions=["states:SendTaskSuccess", "states:SendTaskFailure"],
                resources=["*"],
            )
        )
        table.grant_read_write_data(agent_role)
        key.grant_encrypt_decrypt(agent_role)

        self.agent_worker = lambda_.Function(
            self,
            "AgentWorker",
            function_name=f"autoaws-{cfg.env_name}-agent-worker",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="app.handlers.agent_worker.handler",
            code=code(cfg),
            role=agent_role,
            memory_size=1024,
            timeout=Duration.minutes(5),  # a turn is capped at MAX_AGENT_SECONDS=240
            reserved_concurrent_executions=cfg.agent_concurrency,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=log_group(self, "AgentWorkerLogs"),
            environment={
                **env,
                "LLM_PROVIDER": "bedrock",
                "BEDROCK_MODEL_ID": cfg.bedrock_model_id,
                "BEDROCK_REGION": self.region,
                "BEDROCK_FALLBACK_MODEL": cfg.bedrock_fallback_model,
                "LLM_EFFORT": cfg.llm_effort,
                "MAX_AGENT_SECONDS": "240",
            },
        )
        # Async invocations are never retried: a retry would run the same turn twice.
        self.agent_worker.configure_async_invoke(retry_attempts=0)

        # ---- action-executor: the only writer ------------------------------------------
        executor_role = iam.Role(
            self,
            "ActionExecutorRole",
            role_name=EXECUTOR_ROLE_NAME,
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess"),
            ],
        )
        executor_role.add_to_policy(
            iam.PolicyStatement(
                sid="ApplyApprovedFixes",
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:aws:iam::*:role/{REMEDIATION_ROLE}",
                    # re-reads the target right before writing
                    f"arn:aws:iam::*:role/{READ_ONLY_ROLE}",
                ],
            )
        )
        executor_role.add_to_policy(
            iam.PolicyStatement(
                sid="DeliverEarlyDecision",
                actions=["states:SendTaskSuccess", "states:SendTaskFailure"],
                resources=["*"],
            )
        )
        executor_role.add_to_policy(
            iam.PolicyStatement(
                sid="NoLLM",
                effect=iam.Effect.DENY,
                actions=["bedrock:*", "bedrock-mantle:*"],
                resources=["*"],
            )
        )
        table.grant_read_write_data(executor_role)
        key.grant_encrypt_decrypt(executor_role)

        self.action_executor = lambda_.Function(
            self,
            "ActionExecutor",
            function_name=f"autoaws-{cfg.env_name}-action-executor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="app.handlers.action_executor.handler",
            code=code(cfg),
            role=executor_role,
            memory_size=512,
            timeout=Duration.minutes(2),
            tracing=lambda_.Tracing.ACTIVE,
            log_group=log_group(self, "ActionExecutorLogs"),
            environment={**env, "LLM_PROVIDER": "mock"},  # never calls a model
        )
