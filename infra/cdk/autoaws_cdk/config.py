"""Deployment settings, from CDK context (cdk.json or `-c key=value`)."""

from dataclasses import dataclass
from pathlib import Path

from constructs import Node

ROOT = Path(__file__).resolve().parents[3]  # repo root

# Fixed role names: the customer CloudFormation template trusts exactly these roles
# (backend PLATFORM_AGENT_ROLE_ARN / PLATFORM_EXECUTOR_ROLE_ARN).
AGENT_ROLE_NAME = "autoaws-agent-worker"
EXECUTOR_ROLE_NAME = "autoaws-action-executor"
STATE_MACHINE_NAME = "autoaws-remediation-flow"


@dataclass(frozen=True)
class Config:
    env_name: str  # dev | demo (stack prefix, report §2.8)
    table_name: str
    bedrock_model_id: str
    bedrock_fallback_model: str
    llm_effort: str
    notification_email: str  # proposals waiting / results (SNS email)
    alarm_email: str  # operational alarms and the budget
    budget_usd: int
    frontend_url: str  # links in emails; empty = the CloudFront URL after the first deploy
    agent_concurrency: int  # reserved concurrency of agent-worker (Bedrock quota, cost)
    lambda_asset: Path  # built by build_lambda.sh
    destroy_data: bool  # dev: delete the table (and the user pool) with the stack
    self_sign_up: bool  # anyone can create an account on the Hosted UI (else: admins add users)
    auth_domain_prefix: str  # Hosted UI domain prefix; empty = autodiag-<env>-<account>

    @staticmethod
    def from_context(node: Node) -> "Config":
        def ctx(key: str, default):
            value = node.try_get_context(key)
            return default if value in (None, "") else value

        env_name = ctx("envName", "dev")
        return Config(
            env_name=env_name,
            table_name=ctx("tableName", f"autoaws-{env_name}"),
            bedrock_model_id=ctx("bedrockModelId", "anthropic.claude-opus-5-5"),
            bedrock_fallback_model=ctx("bedrockFallbackModel", "anthropic.claude-opus-4-8"),
            llm_effort=ctx("llmEffort", "high"),
            notification_email=ctx("notificationEmail", ""),
            alarm_email=ctx("alarmEmail", ctx("notificationEmail", "")),
            budget_usd=int(ctx("budgetUsd", 20)),
            frontend_url=ctx("frontendUrl", ""),
            agent_concurrency=int(ctx("agentConcurrency", 5)),
            lambda_asset=Path(ctx("lambdaAsset", str(ROOT / "infra/cdk/build/lambda"))),
            destroy_data=str(ctx("destroyData", env_name == "dev")).lower() == "true",
            self_sign_up=str(ctx("selfSignUp", True)).lower() == "true",
            auth_domain_prefix=ctx("authDomainPrefix", ""),
        )
