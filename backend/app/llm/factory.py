from app.config import get_settings
from app.llm.base import LLMError, LLMProvider


def get_provider() -> LLMProvider:
    name = get_settings().llm_provider
    if name == "mock":
        from app.llm.mock import MockProvider

        return MockProvider()
    if name == "anthropic":
        from app.llm.anthropic import AnthropicProvider

        return AnthropicProvider()
    if name == "bedrock":
        from app.llm.bedrock import BedrockProvider

        return BedrockProvider()
    raise LLMError(f"Unknown LLM_PROVIDER: {name}")
