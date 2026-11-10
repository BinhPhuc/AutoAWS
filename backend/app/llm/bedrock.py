"""BedrockProvider — Claude on Amazon Bedrock (the target LLM, docs/SYSTEM_OVERVIEW.md §7).

Uses the official SDK's Bedrock Mantle client (``anthropic[bedrock]``): the Messages API
served by Bedrock, so tool use, adaptive thinking, effort and prompt caching work as on
the Claude API. Model ids carry the ``anthropic.`` prefix (``anthropic.claude-opus-5-5``).

Credentials are the PLATFORM account's (boto3 default chain / PLATFORM_AWS_PROFILE) — the
user's account is never used to call the model. The IAM role needs Bedrock invoke access
to the chosen model in BEDROCK_REGION.

Refusals: server-side ``fallbacks`` do not exist on Bedrock, so the SDK's client-side
``BetaRefusalFallbackMiddleware`` retries a declined request on BEDROCK_FALLBACK_MODEL
(empty = off). A request declined by every model becomes an LLMError.
"""

from anthropic import AsyncAnthropicBedrockMantle, BetaRefusalFallbackMiddleware

from app.config import get_settings
from app.llm.base import LLMError
from app.llm.claude import ClaudeMessagesProvider


class BedrockProvider(ClaudeMessagesProvider):
    def __init__(self) -> None:
        settings = get_settings()
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
            aws_region=region,
            aws_profile=settings.platform_aws_profile or None,
            middleware=middleware,
        )
        super().__init__(
            name="bedrock",
            client=client,
            model=settings.bedrock_model_id,
            effort=settings.llm_effort,
            max_tokens=settings.llm_max_tokens,
        )
