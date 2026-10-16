"""Provider-neutral LLM interface. PLACEHOLDER: the real provider is not chosen yet.

The agent loop only talks to ``LLMProvider``. A provider converts ``LLMMessage``s and
``ToolSpec``s into its own API format (Anthropic Messages, Bedrock Converse, ...) and
returns an ``LLMResponse`` that is either final text or a list of tool calls.
"""

from typing import Literal, Protocol

from pydantic import BaseModel

from app.aws.registry import ToolSpec


class ToolCallRequest(BaseModel):
    id: str
    name: str
    input: dict = {}


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    # assistant: tool calls it requested in this turn
    tool_calls: list[ToolCallRequest] = []
    # tool: which call this result answers (content is the JSON result)
    tool_call_id: str | None = None
    tool_name: str | None = None


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCallRequest] = []
    stop_reason: str = "end_turn"  # end_turn | tool_use | max_tokens | error

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(Protocol):
    name: str

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        """One model turn. ``messages[0]`` is always the system prompt."""
        ...


class LLMError(Exception):
    """Provider could not produce a response (network, auth, quota, not configured)."""
