"""AnthropicProvider — PLACEHOLDER, not implemented yet.

How to implement (Anthropic Messages API with tool use):
  - pip install anthropic; client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
  - messages[0] (role=system) -> `system=` parameter
  - LLMMessage(role=user)      -> {"role": "user", "content": text}
  - LLMMessage(role=assistant) -> {"role": "assistant", "content": [{"type": "text", ...},
                                   {"type": "tool_use", "id", "name", "input"} ...]}
  - LLMMessage(role=tool)      -> {"role": "user", "content": [{"type": "tool_result",
                                   "tool_use_id": tool_call_id, "content": content}]}
    (consecutive tool messages must be merged into ONE user message)
  - ToolSpec -> {"name", "description", "input_schema"}
  - response.content blocks: text -> LLMResponse.text; tool_use -> ToolCallRequest
  - stop_reason "tool_use" | "end_turn" | "max_tokens"
Keep max_tokens ~2048 and pass the tool list on every turn.
"""

from app.aws.registry import ToolSpec
from app.config import get_settings
from app.llm.base import LLMError, LLMMessage, LLMResponse


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.model = settings.anthropic_model

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        raise NotImplementedError("TODO: implement AnthropicProvider.chat (see module docstring)")
