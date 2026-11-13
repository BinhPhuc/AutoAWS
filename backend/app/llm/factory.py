from app.config import Settings
from app.llm.base import LLMError, LLMProvider


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """The provider of ``settings`` (default: the environment plus the admin's saved choice,
    docs/API_CONTRACT.md §10)."""
    if settings is None:
        from app.llm.config_store import effective_settings  # noqa: PLC0415

        settings = effective_settings()
    name = settings.llm_provider
    if name == "mock":
        from app.llm.mock import MockProvider

        return MockProvider()
    if name == "openai":
        from app.llm.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings)
    if name == "anthropic":
        from app.llm.anthropic import AnthropicProvider

        return AnthropicProvider(settings)
    if name == "bedrock":
        from app.llm.bedrock import BedrockProvider

        return BedrockProvider(settings)
    if name == "mcp":
        from app.llm.mcp_bridge import McpBridgeProvider

        return McpBridgeProvider()
    raise LLMError(f"Unknown LLM_PROVIDER: {name}")
