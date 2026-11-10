"""AutoAws-Api: HTTP API (API Gateway v2) + Lambda api-handler (the FastAPI app via Mangum).

api-handler has NO access to users' accounts: it hands diagnosis to agent-worker (async
invoke), connection checks to agent-worker (sync invoke) and decisions to remediation-flow.
Every route needs a Cognito access token (JWT authorizer, AutoAws-Auth) except the health
check and the sign-in settings the web app reads before signing in.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from .agent import code, common_env, log_group
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
        http_api: apigw.IHttpApi,
        site_url: str,
        user_pool: cognito.IUserPool,
        web_client: cognito.IUserPoolClient,
        hosted_ui_url: str,
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
                **common_env(self, cfg, table, site_url),
                "AGENT_WORKER_FUNCTION": agent_worker.function_name,
                "LLM_PROVIDER": "mock",  # the API never calls a model
                # Served through CloudFront under the same origin; CORS only for the site
                "CORS_ORIGINS": site_url,
                "AUTH_MODE": "cognito",
                "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
                "COGNITO_CLIENT_ID": web_client.user_pool_client_id,
                "COGNITO_DOMAIN": hosted_ui_url,
            },
        )
        integration = integrations.HttpLambdaIntegration(
            "ApiHandlerIntegration",
            self.handler,
            payload_format_version=apigw.PayloadFormatVersion.VERSION_2_0,
        )
        # Imported here (not the Frontend stack's construct): routes and the authorizer must
        # be created in this stack, which may depend on Auth (Frontend may not)
        self.http_api = apigw.HttpApi.from_http_api_attributes(
            self, "HttpApi", http_api_id=http_api.api_id, api_endpoint=http_api.api_endpoint
        )
        # Access tokens of the web client only (the authorizer checks their client_id)
        cognito_auth = authorizers.HttpUserPoolAuthorizer(
            "CognitoAuthorizer", user_pool, user_pool_clients=[web_client]
        )
        apigw.HttpRoute(
            self,
            "DefaultRoute",
            http_api=self.http_api,
            route_key=apigw.HttpRouteKey.DEFAULT,
            integration=integration,
            authorizer=cognito_auth,
        )
        for name, path in (("Health", "/api/health"), ("AuthConfig", "/api/auth/config")):
            apigw.HttpRoute(  # read before signing in
                self,
                f"{name}Route",
                http_api=self.http_api,
                route_key=apigw.HttpRouteKey.with_(path, apigw.HttpMethod.GET),
                integration=integration,
                authorizer=apigw.HttpNoneAuthorizer(),
            )
        apigw.HttpStage(
            self,
            "DefaultStage",
            http_api=self.http_api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=20, burst_limit=40),
        )
