"""Synthesize the platform and check the properties the design depends on (report §2.6)."""

import json

import aws_cdk as cdk
import pytest
from app import build
from aws_cdk.assertions import Match, Template


@pytest.fixture(scope="module")
def stacks(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("CDK_DEFAULT_ACCOUNT", "111122223333")
    mp.setenv("CDK_DEFAULT_REGION", "ap-southeast-1")
    asset = tmp_path_factory.mktemp("lambda")
    (asset / "app").mkdir()
    (asset / "app" / "__init__.py").write_text("")
    app = cdk.App(
        outdir=str(tmp_path_factory.mktemp("cdk.out")),
        context={
            "lambdaAsset": str(asset),
            "notificationEmail": "team@example.com",
            "frontendUrl": "https://d111.cloudfront.net",
            "alarmEmail": "ops@example.com",
        },
    )
    built = build(app)
    out = {name: Template.from_stack(stack) for name, stack in built.items()}
    mp.undo()
    return out


def _statements(template: Template, role_logical_prefix: str) -> list[dict]:
    out = []
    for lid, res in template.to_json()["Resources"].items():
        if res["Type"] == "AWS::IAM::Policy" and lid.startswith(role_logical_prefix):
            out += res["Properties"]["PolicyDocument"]["Statement"]
    return out


def _actions(statements: list[dict], effect: str = "Allow") -> set[str]:
    acts = set()
    for st in statements:
        if st["Effect"] != effect:
            continue
        a = st["Action"]
        acts |= set(a if isinstance(a, list) else [a])
    return acts


def _resources(statements: list[dict], action: str) -> list:
    out = []
    for st in statements:
        a = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
        if action in a and st["Effect"] == "Allow":
            r = st["Resource"]
            out += r if isinstance(r, list) else [r]
    return out


def test_table_is_encrypted_with_ttl_and_pitr(stacks):
    stacks["data"].has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
            "SSESpecification": {"SSEEnabled": True, "SSEType": "KMS"},
            "Replicas": [
                Match.object_like(
                    {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}}
                )
            ],
        },
    )
    stacks["data"].has_resource_properties("AWS::KMS::Key", {"EnableKeyRotation": True})


def test_only_the_executor_can_write_to_user_accounts(stacks):
    agent = stacks["agent"]
    agent_st = _statements(agent, "AgentWorkerRole")
    exec_st = _statements(agent, "ActionExecutorRole")
    assert _resources(agent_st, "sts:AssumeRole") == ["arn:aws:iam::*:role/AutoAWSReadOnly"]
    assert "arn:aws:iam::*:role/AutoAWSRemediation" in _resources(exec_st, "sts:AssumeRole")
    # the LLM side and the writer never mix
    assert "bedrock-mantle:CreateInference" in _actions(agent_st)
    assert {"bedrock:*", "bedrock-mantle:*"} <= _actions(exec_st, effect="Deny")
    # the API cannot reach users' accounts at all
    api_st = _statements(stacks["api"], "ApiHandlerRole")
    assert "sts:AssumeRole" in _actions(api_st, effect="Deny")
    assert "sts:AssumeRole" not in _actions(api_st)


def test_role_names_match_the_customer_template_trust(stacks):
    agent = stacks["agent"]
    agent.has_resource_properties("AWS::IAM::Role", {"RoleName": "autoaws-agent-worker"})
    agent.has_resource_properties("AWS::IAM::Role", {"RoleName": "autoaws-action-executor"})
    env = agent.find_resources("AWS::Lambda::Function")
    for fn in env.values():
        variables = fn["Properties"]["Environment"]["Variables"]
        assert variables["RUNTIME"] == "lambda" and variables["STORAGE_BACKEND"] == "dynamodb"
        assert "role/autoaws-agent-worker" in json.dumps(variables["PLATFORM_AGENT_ROLE_ARN"])


def test_agent_worker_is_bounded_and_never_retried(stacks):
    agent = stacks["agent"]
    agent.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "app.handlers.agent_worker.handler",
            "Runtime": "python3.12",
            "ReservedConcurrentExecutions": 5,
            "Timeout": 300,
            "TracingConfig": {"Mode": "Active"},
        },
    )
    agent.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})


def test_remediation_flow_waits_for_a_person(stacks):
    flow = stacks["workflow"]
    flow.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "StateMachineName": "autoaws-remediation-flow",
            "StateMachineType": "STANDARD",
        },
    )
    text = json.dumps(flow.find_resources("AWS::StepFunctions::StateMachine"))
    assert "waitForTaskToken" in text and '\\"TimeoutSeconds\\":86400' in text
    for state in (
        "Recheck",
        "Execute",
        "Verify",
        "Expire",
        "NotifyPending",
        "NotifyResult",
    ):
        assert state in text
    flow.has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "team@example.com"}
    )


def test_api_is_throttled_and_served_under_the_site(stacks):
    stacks["api"].has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {
            "StageName": "$default",
            "DefaultRouteSettings": {
                "ThrottlingRateLimit": 20,
                "ThrottlingBurstLimit": 40,
            },
        },
    )
    stacks["frontend"].has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": [Match.object_like({"PathPattern": "/api/*"})],
                    "DefaultRootObject": "index.html",
                }
            )
        },
    )
    stacks["frontend"].has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


def test_alarms_and_budget(stacks):
    ops = stacks["ops"]
    assert len(ops.find_resources("AWS::CloudWatch::Alarm")) == 7  # 3 x (errors, throttles) + flow
    ops.has_resource_properties(
        "AWS::Budgets::Budget",
        {"Budget": Match.object_like({"BudgetLimit": {"Amount": 20, "Unit": "USD"}})},
    )


def test_sign_in_is_a_public_pkce_client_on_a_lite_pool(stacks):
    auth = stacks["auth"]
    auth.has_resource_properties("AWS::Cognito::UserPool", {"UserPoolTier": "LITE"})
    auth.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "GenerateSecret": False,
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": Match.array_with(["openid"]),
            "SupportedIdentityProviders": ["COGNITO"],
            "PreventUserExistenceErrors": "ENABLED",
        },
    )
    domains = auth.find_resources("AWS::Cognito::UserPoolDomain")
    for d in domains.values():  # Cognito refuses prefixes containing aws / amazon / cognito
        prefix = json.dumps(d["Properties"]["Domain"]).lower()
        assert not any(word in prefix for word in ("aws", "amazon", "cognito")), prefix


def test_every_api_route_needs_a_token_except_two(stacks):
    api = stacks["api"]
    api.has_resource_properties("AWS::ApiGatewayV2::Authorizer", {"AuthorizerType": "JWT"})
    routes = {
        r["Properties"]["RouteKey"]: r["Properties"].get("AuthorizationType")
        for r in api.find_resources("AWS::ApiGatewayV2::Route").values()
    }
    assert routes == {
        "$default": "JWT",
        "GET /api/health": "NONE",
        "GET /api/auth/config": "NONE",
    }
    fn = next(
        f
        for f in api.find_resources("AWS::Lambda::Function").values()
        if f["Properties"]["Handler"] == "app.handlers.api.handler"
    )
    variables = fn["Properties"]["Environment"]["Variables"]
    assert variables["AUTH_MODE"] == "cognito"
    assert {"COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID", "COGNITO_DOMAIN"} <= set(variables)


def test_spa_fallback_never_rewrites_api_errors(stacks):
    dist = next(iter(stacks["frontend"].find_resources("AWS::CloudFront::Distribution").values()))[
        "Properties"
    ]["DistributionConfig"]
    assert "CustomErrorResponses" not in dist  # would turn API 403/404 into index.html 200
    assert dist["DefaultCacheBehavior"]["FunctionAssociations"][0]["EventType"] == (
        "viewer-request"
    )
    assert "FunctionAssociations" not in dist["CacheBehaviors"][0]  # /api/*


def test_a_custom_domain_replaces_the_cloudfront_url(stacks):
    """frontendUrl set (custom domain): callbacks, CORS and email links use it."""
    client = next(iter(stacks["auth"].find_resources("AWS::Cognito::UserPoolClient").values()))[
        "Properties"
    ]
    assert client["CallbackURLs"] == [
        "https://d111.cloudfront.net/auth/callback",
        "http://localhost:5173/auth/callback",  # envName dev only
    ]
    assert client["LogoutURLs"] == [
        "https://d111.cloudfront.net/",
        "http://localhost:5173/",
    ]


@pytest.fixture(scope="module")
def default_stacks(tmp_path_factory):
    """No frontendUrl (no custom domain): everything must point at CloudFront's own URL."""
    mp = pytest.MonkeyPatch()
    mp.setenv("CDK_DEFAULT_ACCOUNT", "111122223333")
    mp.setenv("CDK_DEFAULT_REGION", "ap-southeast-1")
    asset = tmp_path_factory.mktemp("lambda2")
    (asset / "app").mkdir()
    (asset / "app" / "__init__.py").write_text("")
    app = cdk.App(
        outdir=str(tmp_path_factory.mktemp("cdk.out2")), context={"lambdaAsset": str(asset)}
    )
    built = build(app)
    out = {name: Template.from_stack(stack) for name, stack in built.items()}
    out["_stacks"] = built
    mp.undo()
    return out


def test_one_deploy_sets_up_sign_in(default_stacks):
    """Cognito's callbacks reference the CloudFront distribution directly, so a single
    `cdk deploy --all` is enough (no second deploy with frontendUrl)."""
    client = next(
        iter(default_stacks["auth"].find_resources("AWS::Cognito::UserPoolClient").values())
    )["Properties"]
    first = json.dumps(client["CallbackURLs"][0])
    assert "Fn::ImportValue" in first and "Distribution" in first and "/auth/callback" in first
    fn = next(
        f
        for f in default_stacks["api"].find_resources("AWS::Lambda::Function").values()
        if f["Properties"]["Handler"] == "app.handlers.api.handler"
    )
    variables = fn["Properties"]["Environment"]["Variables"]
    for key in ("FRONTEND_URL", "CORS_ORIGINS"):
        assert "Distribution" in json.dumps(variables[key]), key


def test_stacks_form_a_straight_line(default_stacks):
    """Frontend (CloudFront + bare HTTP API) -> Auth -> Api: no cycle, deployable at once."""
    stacks = default_stacks["_stacks"]

    def deps(name: str) -> set[str]:
        return {d.stack_name for d in stacks[name].dependencies}

    assert deps("frontend") == set()
    assert deps("auth") == {stacks["frontend"].stack_name}
    assert {stacks["auth"].stack_name, stacks["frontend"].stack_name} <= deps("api")
    # the API object lives in Frontend; its stage, routes and authorizer in Api
    assert default_stacks["frontend"].find_resources("AWS::ApiGatewayV2::Route") == {}
    assert len(default_stacks["api"].find_resources("AWS::ApiGatewayV2::Route")) == 3


def test_the_api_signs_external_ids_with_a_generated_key(stacks):
    api = stacks["api"]
    api.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {"GenerateSecretString": Match.object_like({"PasswordLength": 64})},
    )
    fn = next(
        f
        for f in api.find_resources("AWS::Lambda::Function").values()
        if f["Properties"]["Handler"] == "app.handlers.api.handler"
    )
    value = json.dumps(fn["Properties"]["Environment"]["Variables"]["EXTERNAL_ID_SECRET"])
    assert "resolve:secretsmanager" in value  # a dynamic reference, not the key itself
