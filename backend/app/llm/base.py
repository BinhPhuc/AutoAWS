"""Provider-neutral LLM interface.

The agent loop only talks to ``LLMProvider``. A provider converts ``LLMMessage``s and
``ToolSpec``s into its own API format (Bedrock Converse, MCP bridge, ...) and returns an
``LLMResponse`` that is either final text or a list of tool calls (the final answer is
normally the ``submit_diagnosis`` tool call, see app/agent/schemas.py).
"""

from typing import Any, Literal, Protocol

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
    # assistant: the provider's own content blocks for this message (e.g. Bedrock reasoning
    # blocks that must be sent back unchanged). Opaque to the loop; None for history.
    raw: Any = None
    # tool: which call this result answers (content is the JSON result)
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCallRequest] = []
    stop_reason: str = "end_turn"  # end_turn | tool_use | max_tokens | error
    raw: Any = None  # provider content blocks, copied into the assistant LLMMessage
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(Protocol):
    name: str
    # False for providers that wait on a human-paced client (MCP bridge): the loop then
    # skips its wall-clock limit (MAX_AGENT_SECONDS).
    enforce_time_limit: bool

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        """One model turn. ``messages[0]`` is always the system prompt."""
        ...


class LLMError(Exception):
    """Provider could not produce a response (network, auth, quota, not configured)."""
