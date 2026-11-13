"""AnthropicProvider — the Messages API through the official ``anthropic`` SDK.

Two uses:
- Claude API (``ANTHROPIC_API_KEY``, ``sk-ant-…``): dev alternative to Bedrock, same request
  as BedrockProvider (app/llm/claude.py). Refusals use the server-side fallback in its
  "default" form, which routes a declined request by refusal category.
- A gateway that speaks the Messages API (``ANTHROPIC_BASE_URL`` + ``ANTHROPIC_AUTH_TOKEN``,
  the settings such services give for Claude Code), possibly serving other models behind
  it: compatibility mode, only the basic request (``claude_features=False``). Demo only:
  the question and the sanitized AWS data pass through that gateway.
"""

from anthropic import AsyncAnthropic

from app.config import Settings, get_settings
from app.llm.base import LLMError
from app.llm.claude import ClaudeMessagesProvider


class AnthropicProvider(ClaudeMessagesProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        if not s.anthropic_model:
            raise LLMError("ANTHROPIC_MODEL is not set")
        gateway = bool(s.anthropic_base_url)
        if gateway:
            if not (s.anthropic_auth_token or s.anthropic_api_key):
                raise LLMError("ANTHROPIC_BASE_URL is set: also set ANTHROPIC_AUTH_TOKEN")
            client = AsyncAnthropic(
                base_url=s.anthropic_base_url.rstrip("/"),
                auth_token=s.anthropic_auth_token or None,  # Authorization: Bearer
                api_key=None if s.anthropic_auth_token else s.anthropic_api_key,
            )
        else:
            if not s.anthropic_api_key:
                raise LLMError("ANTHROPIC_API_KEY is not set")
            client = AsyncAnthropic(api_key=s.anthropic_api_key)
        super().__init__(
            name="anthropic",
            client=client,
            model=s.anthropic_model,
            effort=s.llm_effort,
            max_tokens=s.llm_max_tokens,
            extra={}
            if gateway
            else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"},
            claude_features=not gateway,
            gateway_cache=gateway and s.anthropic_gateway_cache,
        )
