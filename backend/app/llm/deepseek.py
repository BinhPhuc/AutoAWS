"""Direct DeepSeek Chat Completions using the SDK documented by DeepSeek.

Only the LLM transport changes; the agent owns tool execution and sanitization.
Reasoning content is opaque, in-memory context for subsequent tool rounds.
"""

import httpx
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
)
from openai.types.chat import ChatCompletion

from app.aws.registry import ToolSpec
from app.config import get_settings
from app.llm.base import LLMError, LLMMessage, LLMResponse
from app.llm.openai_compatible import _message, _response


class DeepSeekProvider:
    name = "deepseek"
    enforce_time_limit = True

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        settings = get_settings()
        key = settings.deepseek_api_key.get_secret_value().strip()
        if not key:
            raise LLMError("Set DEEPSEEK_API_KEY to a key issued by the DeepSeek platform")
        model = settings.deepseek_model.strip()
        if not model:
            raise LLMError("Set DEEPSEEK_MODEL to a model available on the DeepSeek API")

        request_messages = []
        for message in messages:
            item = _message(message)
            if message.role == "assistant" and isinstance(message.raw, dict):
                reasoning = message.raw.get("reasoning_content")
                if isinstance(reasoning, str):
                    item["reasoning_content"] = reasoning
            request_messages.append(item)

        request = {
            "model": model,
            "messages": request_messages,
            "max_tokens": settings.deepseek_max_tokens,
            "stream": False,
            "extra_body": {
                "thinking": {"type": "enabled" if settings.deepseek_thinking else "disabled"}
            },
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

        try:
            async with AsyncOpenAI(
                api_key=key,
                base_url="https://api.deepseek.com",
                timeout=settings.deepseek_timeout_seconds,
                # The agent owns its time/token budget; avoid hidden SDK retries.
                max_retries=0,
                http_client=httpx.AsyncClient(transport=self._transport, follow_redirects=False),
            ) as client:
                completion = await client.chat.completions.create(**request)
        except APITimeoutError:
            raise LLMError(
                "DeepSeek request timed out; try again or increase DEEPSEEK_TIMEOUT_SECONDS"
            ) from None
        except APIConnectionError:
            raise LLMError("Could not reach the DeepSeek API; check network connectivity") from None
        except APIStatusError as exc:
            # Remote errors and exception strings may echo keys or user data.
            hints = {
                400: "check DEEPSEEK_MODEL and tool-calling request settings",
                401: "check DEEPSEEK_API_KEY",
                402: "insufficient balance; top up the DeepSeek API account",
                403: "check the API key's permissions",
                404: "check DEEPSEEK_MODEL",
                422: "check request parameters and tool schemas",
                429: "rate limited; try again later",
                500: "DeepSeek server error; try again later",
                503: "DeepSeek is overloaded; try again later",
            }
            hint = hints.get(exc.status_code, "check DeepSeek API availability")
            raise LLMError(f"DeepSeek request failed (HTTP {exc.status_code}); {hint}") from None
        except (APIResponseValidationError, ValueError):
            raise LLMError("DeepSeek returned an invalid Chat Completions response") from None
        except OpenAIError:
            raise LLMError("DeepSeek SDK could not complete the request") from None

        if not isinstance(completion, ChatCompletion):
            raise LLMError("DeepSeek returned an invalid Chat Completions response")
        payload = completion.model_dump()
        try:
            response = _response(payload)
        except LLMError as exc:
            raise LLMError(str(exc).replace("OpenAI-compatible", "DeepSeek")) from None
        reasoning = payload["choices"][0]["message"].get("reasoning_content")
        if isinstance(reasoning, str):
            response.raw = {"reasoning_content": reasoning}
        return response
