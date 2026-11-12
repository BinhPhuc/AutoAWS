"""Claude through the Messages API — shared by BedrockProvider and AnthropicProvider.

Both platforms serve the same Messages API through the official ``anthropic`` SDK; only
the client differs (``AsyncAnthropicBedrockMantle`` vs ``AsyncAnthropic``). Mapping:

  messages[0] (system)      -> ``system`` (byte-identical every round: prompt caching)
  user                      -> user message (text)
  assistant (this turn)     -> the content blocks the API returned, unchanged (``raw``):
                               thinking blocks must be sent back exactly as received
  assistant (history)       -> plain text (earlier turns are replayed as summaries)
  tool results              -> ``tool_result`` blocks, all results of one step in ONE user
                               message (``is_error`` for failures); a following loop
                               instruction (finalize / retry) joins that message as text
  ToolSpec                  -> ``{name, description, input_schema}``; tool_choice stays auto
                               (forced tool use is rejected by current models)

Thinking is adaptive and depth is set with ``output_config.effort`` (Claude Opus 5.5
defaults to ``medium``, so the effort is always sent). Requests stream and are collected
with ``get_final_message()`` because tool results can make inputs long.
"""

import asyncio
import logging
from typing import Any

import anthropic

from app.aws.registry import ToolSpec
from app.llm.base import LLMError, LLMMessage, LLMResponse, ToolCallRequest

log = logging.getLogger(__name__)

# The SDK retries failed HTTP responses itself, but not an `error` event that arrives inside
# a stream which started with 200 (gateways relay upstream failures this way). One such
# blip would otherwise throw away every tool call of the turn.
STREAM_ATTEMPTS = 3


def to_messages(messages: list[LLMMessage]) -> tuple[str, list[dict]]:
    """(system, Messages API messages) from the loop's provider-neutral messages."""
    system = messages[0].content if messages and messages[0].role == "system" else ""
    out: list[dict] = []

    def append(role: str, blocks: list[dict]) -> None:
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)  # tool results + loop note in one user turn
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        if m.role == "system":
            continue
        if m.role == "user":
            append("user", [{"type": "text", "text": m.content}])
        elif m.role == "tool":
            append(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": m.content,
                        "is_error": m.is_error,
                    }
                ],
            )
        elif m.raw:
            append("assistant", list(m.raw))
        else:
            blocks: list[dict] = [{"type": "text", "text": m.content}] if m.content else []
            blocks += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
                for c in m.tool_calls
            ]
            append("assistant", blocks or [{"type": "text", "text": "(no content)"}])
    return system, out


def to_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def with_cache_breakpoints(req: dict) -> dict:
    """Explicit ``cache_control`` breakpoints (gateways may not know the top-level form):
    the system prompt, the last tool (caches every tool before it) and the last block of the
    latest message (the next round reads this whole prefix from the cache). 3 of the 4
    breakpoints the Messages API allows."""
    mark = {"type": "ephemeral"}
    out = dict(req)
    if out.get("system"):
        out["system"] = [{"type": "text", "text": out["system"], "cache_control": mark}]
    if out.get("tools"):
        out["tools"] = [*out["tools"][:-1], {**out["tools"][-1], "cache_control": mark}]
    if out.get("messages"):
        last = out["messages"][-1]
        blocks = list(last["content"])
        if blocks:
            blocks[-1] = {**blocks[-1], "cache_control": mark}
        out["messages"] = [*out["messages"][:-1], {**last, "content": blocks}]
    return out


def from_message(message: Any) -> LLMResponse:
    """LLMResponse from an SDK message; refusals and truncation become LLMError."""
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise LLMError(f"the model declined the request (refusal, category {category})")
    if message.stop_reason == "max_tokens":
        raise LLMError("the model reached max_tokens before finishing; raise its max_tokens")

    texts, calls, raw = [], [], []
    for block in message.content:
        raw.append(block.to_dict())
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            calls.append(ToolCallRequest(id=block.id, name=block.name, input=block.input or {}))
    usage = message.usage
    input_tokens = (
        (usage.input_tokens or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    )
    return LLMResponse(
        text="\n".join(texts) or None,
        tool_calls=calls,
        stop_reason=message.stop_reason or "end_turn",
        raw=raw,
        input_tokens=input_tokens,
        output_tokens=usage.output_tokens or 0,
    )


class ClaudeMessagesProvider:
    """One model turn over the Messages API (``client.beta.messages``)."""

    enforce_time_limit = True

    def __init__(
        self,
        name: str,
        client: Any,
        model: str,
        effort: str,
        max_tokens: int,
        extra: dict | None = None,
        claude_features: bool = True,
        gateway_cache: bool = False,
    ) -> None:
        self.name = name
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.extra = extra or {}
        # False: a third-party Messages API gateway — send only the basic request
        self.claude_features = claude_features
        self.gateway_cache = gateway_cache

    def request(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> dict:
        system, api_messages = to_messages(messages)
        if not self.claude_features:
            req = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": api_messages,
                "tools": to_tools(tools),
            }
            return with_cache_breakpoints(req) if self.gateway_cache else req
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": api_messages,
            "tools": to_tools(tools),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            # Automatic caching: tools + system + earlier rounds are an identical prefix.
            "cache_control": {"type": "ephemeral"},
            **self.extra,
        }

    async def _stream(self, api: Any, params: dict) -> Any:
        for attempt in range(1, STREAM_ATTEMPTS + 1):
            try:
                async with api.stream(**params) as stream:
                    return await stream.get_final_message()
            except anthropic.APIStatusError as e:
                transient = e.status_code == 200 or e.status_code >= 500
                if not transient or attempt == STREAM_ATTEMPTS:
                    raise
                log.warning(
                    "%s: error in the response (%s %s), retry %d/%d",
                    self.name,
                    e.status_code,
                    e.message,
                    attempt,
                    STREAM_ATTEMPTS - 1,
                )
                await asyncio.sleep(2 * attempt)
        raise AssertionError("unreachable")

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        params = self.request(messages, tools)
        try:
            # Gateways get the plain endpoint (the beta one adds ?beta=true)
            api = self.client.beta.messages if self.claude_features else self.client.messages
            message = await self._stream(api, params)
        except anthropic.AuthenticationError as e:
            raise LLMError(f"{self.name}: authentication failed ({e.message})") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError(f"{self.name}: no access to model {self.model} ({e.message})") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"{self.name}: model {self.model} not found ({e.message})") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"{self.name}: rate limited, try again shortly") from e
        except anthropic.BadRequestError as e:
            log.error("Bad request to %s: %s", self.name, e.message)
            raise LLMError(f"{self.name}: request rejected ({e.message})") from e
        except anthropic.APIStatusError as e:
            log.error("%s: API error %s: %s", self.name, e.status_code, e.message)
            raise LLMError(f"{self.name}: API error {e.status_code} ({e.message})") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"{self.name}: cannot reach the API") from e
        response = from_message(message)
        usage = message.usage
        log.info(
            "%s %s: stop=%s tools=%d in=%d out=%d cache_read=%d cache_write=%d",
            self.name,
            self.model,
            response.stop_reason,
            len(response.tool_calls),
            response.input_tokens,
            response.output_tokens,
            getattr(usage, "cache_read_input_tokens", 0) or 0,
            getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
        return response
