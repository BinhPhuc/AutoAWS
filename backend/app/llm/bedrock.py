"""BedrockProvider — PLACEHOLDER, not implemented yet.

How to implement (Bedrock Converse API with toolConfig):
  - client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
    (use the platform session; run the blocking call in asyncio.to_thread)
  - messages[0] (role=system) -> `system=[{"text": ...}]`
  - user      -> {"role": "user", "content": [{"text": ...}]}
  - assistant -> {"role": "assistant", "content": [{"text": ...}, {"toolUse": {"toolUseId",
                 "name", "input"}}]}
  - tool      -> {"role": "user", "content": [{"toolResult": {"toolUseId": tool_call_id,
                 "content": [{"json": <dict>}]}}]}  (merge consecutive tool messages)
  - ToolSpec  -> {"toolSpec": {"name", "description", "inputSchema": {"json": input_schema}}}
  - response["output"]["message"]["content"]: text / toolUse blocks
  - response["stopReason"]: "tool_use" | "end_turn" | "max_tokens"
Optionally attach a Guardrail (guardrailConfig) for extra PII masking.
"""

from app.aws.registry import ToolSpec
from app.config import get_settings
from app.llm.base import LLMError, LLMMessage, LLMResponse


class BedrockProvider:
    name = "bedrock"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.bedrock_model_id:
            raise LLMError("BEDROCK_MODEL_ID is not set")
        self.model_id = settings.bedrock_model_id
        self.region = settings.bedrock_region or None

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        raise NotImplementedError("TODO: implement BedrockProvider.chat (see module docstring)")
