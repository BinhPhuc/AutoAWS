"""OpenAI-compatible Chat Completions with function calling, including local Ollama.

Only the protocol is shared: the endpoint, model and optional key come from Settings.
AWS access and tool execution remain in the existing agent loop and fixed registry.
"""

import json
from typing import Any

import httpx

from app.aws.registry import ToolSpec
from app.config import get_settings
from app.llm.base import LLMError, LLMMessage, LLMResponse, ToolCallRequest


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        settings = get_settings()
        if not settings.openai_model.strip():
            raise LLMError("Set OPENAI_MODEL to a model served by your OpenAI-compatible endpoint")
        try:
            base_url = httpx.URL(settings.openai_base_url.strip())
        except httpx.InvalidURL:
            raise LLMError("OPENAI_BASE_URL must be a valid HTTP(S) API base URL") from None
        if (
            base_url.scheme not in {"http", "https"}
            or not base_url.host
            or base_url.userinfo
            or base_url.query
            or base_url.fragment
        ):
            raise LLMError(
                "OPENAI_BASE_URL must be HTTP(S), without credentials, query or fragment"
            )

        request: dict[str, Any] = {
            "model": settings.openai_model.strip(),
            "messages": [_message(message) for message in messages],
            "stream": False,
            settings.openai_token_limit_field: settings.openai_max_tokens,
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in tools
            ]
            request["tool_choice"] = "auto"

        headers = {}
        if key := settings.openai_api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {key}"
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=settings.openai_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{str(base_url).rstrip('/')}/chat/completions", json=request, headers=headers
                )
        except httpx.TimeoutException:
            raise LLMError(
                "OpenAI-compatible request timed out; check the server or increase "
                "OPENAI_TIMEOUT_SECONDS for model loading"
            ) from None
        except (httpx.RequestError, httpx.InvalidURL):
            raise LLMError(
                "Could not reach the OpenAI-compatible server; check OPENAI_BASE_URL "
                "and that the model server is running"
            ) from None
        if response.status_code != 200:
            # Never echo remote payloads: gateways can include keys or user input in errors.
            hints = {
                400: "check the model's tool-calling support and request settings",
                401: "check OPENAI_API_KEY",
                403: "check the API key's model permissions",
                404: "check OPENAI_BASE_URL (include /v1) and OPENAI_MODEL; pull the Ollama model",
                429: "the server is rate limited or out of quota; try again later",
            }
            hint = hints.get(response.status_code, "check the model server and its availability")
            raise LLMError(
                f"OpenAI-compatible request failed (HTTP {response.status_code}); {hint}"
            )
        try:
            payload = response.json()
        except ValueError:
            raise LLMError("OpenAI-compatible server returned invalid JSON") from None
        return _response(payload)


def _message(message: LLMMessage) -> dict[str, Any]:
    result: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        result["content"] = message.content or None
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.input, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    if message.role == "tool":
        if not message.tool_call_id:
            raise LLMError("Tool result is missing its tool_call_id")
        result["tool_call_id"] = message.tool_call_id
    return result


def _response(payload: Any) -> LLMResponse:
    malformed = "OpenAI-compatible server returned an invalid Chat Completions response"
    if not isinstance(payload, dict):
        raise LLMError(malformed)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMError(malformed)
    choice = choices[0]
    if choice.get("finish_reason") not in ("stop", "tool_calls"):
        raise LLMError(
            "OpenAI-compatible response was incomplete or blocked; "
            "check the model output limit and server settings"
        )
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise LLMError(malformed)
    text = message.get("content")
    if text is not None and not isinstance(text, str):
        raise LLMError(malformed)
    raw_calls = message.get("tool_calls")
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list):
        raise LLMError(malformed)
    calls = []
    ids: set[str] = set()
    for raw in raw_calls:
        if not isinstance(raw, dict) or raw.get("type") != "function":
            raise LLMError(malformed)
        call_id, function = raw.get("id"), raw.get("function")
        if not isinstance(call_id, str) or not call_id.strip() or call_id in ids:
            raise LLMError(malformed)
        if not isinstance(function, dict):
            raise LLMError(malformed)
        name, arguments = function.get("name"), function.get("arguments")
        if not isinstance(name, str) or not name.strip() or not isinstance(arguments, str):
            raise LLMError(malformed)
        try:
            inputs = json.loads(arguments)
        except ValueError:
            raise LLMError("OpenAI-compatible model returned invalid JSON tool arguments") from None
        if not isinstance(inputs, dict):
            raise LLMError("OpenAI-compatible tool arguments must be a JSON object")
        ids.add(call_id)
        calls.append(ToolCallRequest(id=call_id, name=name, input=inputs))
    if calls:
        return LLMResponse(text=text, tool_calls=calls, stop_reason="tool_use")
    if choice["finish_reason"] == "tool_calls" or not text or not text.strip():
        raise LLMError("OpenAI-compatible model returned an empty response")
    return LLMResponse(text=text, stop_reason="end_turn")
