"""Amazon Bedrock Converse adapter for the provider-neutral agent loop."""

import asyncio
import json
from typing import Any

from app.aws.bedrock import converse
from app.aws.registry import ToolSpec
from app.config import get_settings
from app.llm.base import LLMError, LLMMessage, LLMResponse, ToolCallRequest


class BedrockProvider:
    name = "bedrock"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.bedrock_model_id:
            raise LLMError("BEDROCK_MODEL_ID is not set")
        self.model_id = settings.bedrock_model_id
        self.region = settings.bedrock_region or None

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        system = []
        turns: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                system.append({"text": message.content})
                continue
            blocks: list[dict[str, Any]] = []
            role = message.role
            if role == "tool":
                role = "user"
                if not message.tool_call_id:
                    raise LLMError("Tool result is missing its call ID")
                try:
                    result = json.loads(message.content)
                except ValueError:
                    raise LLMError("Tool result is not valid JSON") from None
                blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": message.tool_call_id,
                            "content": [{"json": result}],
                            "status": "error"
                            if isinstance(result, dict) and "error" in result
                            else "success",
                        }
                    }
                )
            else:
                if message.content:
                    blocks.append({"text": message.content})
                blocks.extend(
                    {
                        "toolUse": {
                            "toolUseId": call.id,
                            "name": call.name,
                            "input": call.input,
                        }
                    }
                    for call in message.tool_calls
                )
            if not blocks:
                raise LLMError("Empty conversation message")
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"].extend(blocks)
            else:
                turns.append({"role": role, "content": blocks})

        request: dict[str, Any] = {
            "modelId": self.model_id,
            "system": system,
            "messages": turns,
            "inferenceConfig": {"maxTokens": 2048},
        }
        if tools:
            request["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": {"json": tool.input_schema},
                        }
                    }
                    for tool in tools
                ]
            }
        response = await asyncio.to_thread(converse, self.region, request)
        try:
            reason = response["stopReason"]
            blocks = response["output"]["message"]["content"]
            text = "\n".join(block["text"] for block in blocks if "text" in block)
            calls = [
                ToolCallRequest(
                    id=block["toolUse"]["toolUseId"],
                    name=block["toolUse"]["name"],
                    input=block["toolUse"]["input"],
                )
                for block in blocks
                if "toolUse" in block
            ]
        except (KeyError, TypeError, ValueError):
            raise LLMError("Malformed Bedrock response") from None
        if reason not in ("end_turn", "tool_use"):
            raise LLMError("Bedrock did not complete its response")
        if (reason == "tool_use") != bool(calls) or (not calls and not text.strip()):
            raise LLMError("Incomplete Bedrock response")
        return LLMResponse(text=text or None, tool_calls=calls, stop_reason=reason)
