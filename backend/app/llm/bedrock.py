"""BedrockProvider — Claude on Amazon Bedrock (the target LLM, docs/SYSTEM_OVERVIEW.md §7).

Uses the official SDK's Bedrock Mantle client (``anthropic[bedrock]``): the Messages API
served by Bedrock, so tool use, adaptive thinking, effort and prompt caching work as on
the Claude API. Model ids carry the ``anthropic.`` prefix (``anthropic.claude-opus-5-5``).

How calls are signed (``BEDROCK_AUTH``, or the admin's choice, docs/API_CONTRACT.md §10):
- ``iam``: the PLATFORM account's own credentials (Lambda role / PLATFORM_AWS_PROFILE).
- ``api_key``: a Bedrock API key (``Authorization: Bearer``).
- ``access_key``: an IAM user's access key pair with Bedrock access.
- ``assume_role``: the platform assumes a role (e.g. in another account that has Bedrock)
  and signs with its temporary credentials, renewed before a job could outlive them.
The user's account is never used to call the model.

Refusals: server-side ``fallbacks`` do not exist on Bedrock, so the SDK's client-side
``BetaRefusalFallbackMiddleware`` retries a declined request on BEDROCK_FALLBACK_MODEL
(empty = off). A request declined by every model becomes an LLMError.
"""

import threading
from datetime import UTC, datetime, timedelta

from anthropic import AsyncAnthropicBedrockMantle, BetaRefusalFallbackMiddleware

from app.config import Settings, get_settings
from app.llm.base import LLMError
from app.llm.claude import ClaudeMessagesProvider

_role_lock = threading.Lock()
# (role_arn, external_id) -> (credentials dict, expiration)
_role_cache: dict[tuple[str, str], tuple[dict, datetime]] = {}


def _assumed_credentials(settings: Settings) -> dict:
    """Temporary credentials of BEDROCK_ROLE_ARN, reused only while they outlive a job."""
    from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

    from app.aws.credentials import platform_session  # noqa: PLC0415

    key = (settings.bedrock_role_arn, settings.bedrock_external_id)
    margin = timedelta(seconds=settings.max_agent_seconds + 60)
    with _role_lock:
        cached = _role_cache.get(key)
        if cached and cached[1] - margin > datetime.now(UTC):
            return cached[0]
    kwargs = {"RoleArn": settings.bedrock_role_arn, "RoleSessionName": "autoaws-bedrock"}
    if settings.bedrock_external_id:
        kwargs["ExternalId"] = settings.bedrock_external_id
    try:
        creds = platform_session().client("sts").assume_role(**kwargs)["Credentials"]
    except (ClientError, BotoCoreError) as e:
        raise LLMError(f"bedrock: could not assume {settings.bedrock_role_arn} ({e})") from e
    expiration = creds["Expiration"]
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=UTC)
    with _role_lock:
        _role_cache[key] = (creds, expiration)
    return creds


def _auth_kwargs(settings: Settings) -> dict:
    auth = settings.bedrock_auth
    if auth == "api_key":
        key = settings.bedrock_api_key.get_secret_value()
        if not key:
            raise LLMError("bedrock: auth is api_key but no Bedrock API key is set")
        return {"api_key": key}
    if auth == "access_key":
        secret = settings.bedrock_secret_access_key.get_secret_value()
        if not settings.bedrock_access_key_id or not secret:
            raise LLMError("bedrock: auth is access_key but the key pair is incomplete")
        return {"aws_access_key": settings.bedrock_access_key_id, "aws_secret_key": secret}
    if auth == "assume_role":
        if not settings.bedrock_role_arn:
            raise LLMError("bedrock: auth is assume_role but no role ARN is set")
        creds = _assumed_credentials(settings)
        return {
            "aws_access_key": creds["AccessKeyId"],
            "aws_secret_key": creds["SecretAccessKey"],
            "aws_session_token": creds["SessionToken"],
        }
    return {"aws_profile": settings.platform_aws_profile or None}


class BedrockProvider(ClaudeMessagesProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        region = settings.bedrock_region or settings.dynamodb_region
        if not settings.bedrock_model_id:
            raise LLMError("BEDROCK_MODEL_ID is not set")
        if not region:
            raise LLMError("BEDROCK_REGION is not set")
        middleware = (
            [BetaRefusalFallbackMiddleware([{"model": settings.bedrock_fallback_model}])]
            if settings.bedrock_fallback_model
            else None
        )
        client = AsyncAnthropicBedrockMantle(
            aws_region=region, middleware=middleware, **_auth_kwargs(settings)
        )
        super().__init__(
            name="bedrock",
            client=client,
            model=settings.bedrock_model_id,
            effort=settings.llm_effort,
            max_tokens=settings.llm_max_tokens,
        )
