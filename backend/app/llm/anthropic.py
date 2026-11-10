"""AnthropicProvider — Claude through the Claude API (dev alternative to Bedrock).

Same request as BedrockProvider (app/llm/claude.py); only the client differs. Refusals use
the server-side fallback in its "default" form, which routes a declined request by
refusal category without a model list to maintain.
"""

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.llm.base import LLMError
from app.llm.claude import ClaudeMessagesProvider


class AnthropicProvider(ClaudeMessagesProvider):
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        if not settings.anthropic_model:
            raise LLMError("ANTHROPIC_MODEL is not set")
        super().__init__(
            name="anthropic",
            client=AsyncAnthropic(api_key=settings.anthropic_api_key),
            model=settings.anthropic_model,
            effort=settings.llm_effort,
            max_tokens=settings.llm_max_tokens,
            extra={"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"},
        )
