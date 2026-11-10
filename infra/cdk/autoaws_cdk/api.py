"""AutoAws-Api: HTTP API (API Gateway v2) + Lambda api-handler (the FastAPI app via Mangum).

api-handler has NO access to users' accounts: it hands diagnosis to agent-worker (async
invoke), connection checks to agent-worker (sync invoke) and decisions to remediation-flow.
Cognito JWT authorization protects business routes; health and auth config are public.
"""

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from .agent import code, common_env, log_group
from .auth import AuthStack
from .config import Config


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        cfg: Config,
        table: ddb.ITableV2,
        key: kms.IKey,
        agent_worker: lambda_.IFunction,
        auth: AuthStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        role = iam.Role(
            self,
            "ApiHandlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess"),
            ],
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="DeliverDecisions",
                actions=["states:SendTaskSuccess", "states:SendTaskFailure"],
                resources=["*"],  # task tokens are not resources
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="NoUserAccounts",
                effect=iam.Effect.DENY,
                actions=["sts:AssumeRole"],
                resources=["*"],
            )
        )
        table.grant_read_write_data(role)
        key.grant_encrypt_decrypt(role)
        agent_worker.grant_invoke(role)

        self.handler = lambda_.Function(
            self,
            "ApiHandler",
            function_name=f"autoaws-{cfg.env_name}-api-handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="app.handlers.api.handler",
            code=code(cfg),
            role=role,
            memory_size=512,
            timeout=Duration.seconds(29),  # API Gateway integration limit is 30 s
            tracing=lambda_.Tracing.ACTIVE,
            log_group=log_group(self, "ApiHandlerLogs"),
            environment={
                **common_env(self, cfg, table),
                "AGENT_WORKER_FUNCTION": agent_worker.function_name,
                "LLM_PROVIDER": "mock",  # the API never calls a model
                "AUTH_MODE": "cognito",
                "COGNITO_ISSUER": auth.issuer,
                "COGNITO_CLIENT_ID": auth.client.user_pool_client_id,
                "COGNITO_DOMAIN": auth.domain,
                # Served through CloudFront under the same origin; CORS only for frontendUrl
                "CORS_ORIGINS": cfg.frontend_url or "https://localhost",
            },
        )
        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=f"autoaws-{cfg.env_name}",
            create_default_stage=False,
            default_authorizer=authorizers.HttpJwtAuthorizer(
                "CognitoJwt",
                auth.issuer,
                jwt_audience=[auth.client.user_pool_client_id],
            ),
            default_authorization_scopes=["openid"],
            default_integration=integrations.HttpLambdaIntegration(
                "ApiHandlerIntegration",
                self.handler,
                payload_format_version=apigw.PayloadFormatVersion.VERSION_2_0,
            ),
        )
        public_integration = integrations.HttpLambdaIntegration("PublicApi", self.handler)
        for path in ("/api/health", "/api/auth/config"):
            self.http_api.add_routes(
                path=path,
                methods=[apigw.HttpMethod.GET],
                integration=public_integration,
                authorizer=apigw.HttpNoneAuthorizer(),
            )
        self.http_api.add_stage(
            "DefaultStage",
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=20, burst_limit=40),
        )
        CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
