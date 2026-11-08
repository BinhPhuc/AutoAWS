"""Claude providers (Bedrock Mantle / Claude API): request mapping and response handling.

No network: the SDK client is replaced by a fake that records the request and returns a
real SDK message object.
"""

import pytest
from anthropic.types.beta import BetaMessage

from app.agent.loop import llm_tools
from app.aws.registry import list_tools
from app.llm.base import LLMError, LLMMessage, ToolCallRequest
from app.llm.claude import ClaudeMessagesProvider, from_message, to_messages


def _message(content: list[dict], stop_reason: str = "end_turn", **extra) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "anthropic.claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 0,
            },
            **extra,
        }
    )


class _FakeStream:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self.message


class _FakeClient:
    def __init__(self, message):
        self.requests: list[dict] = []
        outer = self

        class _Messages:
            def stream(self, **params):
                outer.requests.append(params)
                return _FakeStream(message)

        self.beta = type("Beta", (), {"messages": _Messages()})()


def test_tool_results_of_one_step_share_one_user_message():
    raw = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "tool_use", "id": "t1", "name": "describe_instances", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "describe_route_tables", "input": {}},
    ]
    system, msgs = to_messages(
        [
            LLMMessage(role="system", content="SYS"),
            LLMMessage(role="user", content="Hỏi lượt trước"),
            LLMMessage(role="assistant", content="[Answer]\n{...}"),  # history: plain text
            LLMMessage(role="user", content="Câu hỏi"),
            LLMMessage(
                role="assistant",
                tool_calls=[ToolCallRequest(id="t1", name="describe_instances")],
                raw=raw,
            ),
            LLMMessage(role="tool", tool_call_id="t1", tool_name="x", content='{"a": 1}'),
            LLMMessage(role="tool", tool_call_id="t2", tool_name="y", content="{}", is_error=True),
            LLMMessage(role="user", content="[Limit reached: the time limit] ..."),
        ]
    )
    assert system == "SYS"
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert msgs[3]["content"] == raw  # this turn's blocks go back unchanged (thinking!)
    last = msgs[4]["content"]
    assert [b["type"] for b in last] == ["tool_result", "tool_result", "text"]
    assert last[1]["is_error"] is True and last[0]["tool_use_id"] == "t1"


def test_response_tool_calls_usage_and_raw_blocks():
    msg = _message(
        [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": "Đọc route table."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "describe_route_tables",
                "input": {"subnet_ids": ["subnet-1"]},
            },
        ],
        stop_reason="tool_use",
    )
    r = from_message(msg)
    assert r.text == "Đọc route table."
    assert [(c.id, c.name, c.input) for c in r.tool_calls] == [
        ("toolu_1", "describe_route_tables", {"subnet_ids": ["subnet-1"]})
    ]
    assert r.input_tokens == 1000 and r.output_tokens == 20  # cached input counts too
    assert r.raw[0]["type"] == "thinking" and r.raw[0]["signature"] == "sig"


def test_refusal_and_max_tokens_become_llm_errors():
    with pytest.raises(LLMError, match="declined"):
        from_message(_message([], stop_reason="refusal"))
    with pytest.raises(LLMError, match="max_tokens"):
        from_message(_message([{"type": "text", "text": "..."}], stop_reason="max_tokens"))


async def test_request_shape():
    client = _FakeClient(_message([{"type": "text", "text": "{}"}]))
    provider = ClaudeMessagesProvider("bedrock", client, "anthropic.claude-opus-5-5", "high", 16000)
    await provider.chat(
        [LLMMessage(role="system", content="SYS"), LLMMessage(role="user", content="Hỏi")],
        llm_tools(list_tools()),
    )
    [req] = client.requests
    assert req["model"] == "anthropic.claude-opus-5-5" and req["system"] == "SYS"
    assert req["thinking"] == {"type": "adaptive"}
    assert req["output_config"] == {"effort": "high"}
    assert req["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in req and "temperature" not in req
    names = [t["name"] for t in req["tools"]]
    assert names[-1] == "submit_diagnosis" and "describe_instances" in names
    assert set(req["tools"][0]) == {"name", "description", "input_schema"}


async def test_api_errors_become_llm_errors():
    import anthropic
    import httpx2

    class Failing(_FakeClient):
        def __init__(self):
            super().__init__(None)
            request = httpx2.Request("POST", "https://bedrock-mantle.example/v1/messages")
            response = httpx2.Response(429, request=request)

            class _Messages:
                def stream(self, **params):
                    raise anthropic.RateLimitError("slow down", response=response, body=None)

            self.beta = type("Beta", (), {"messages": _Messages()})()

    provider = ClaudeMessagesProvider("bedrock", Failing(), "m", "high", 100)
    with pytest.raises(LLMError, match="rate limited"):
        await provider.chat([LLMMessage(role="system", content="S")], [])


def test_bedrock_provider_builds_the_mantle_client(monkeypatch):
    from anthropic import AsyncAnthropicBedrockMantle

    from app.config import get_settings
    from app.llm.bedrock import BedrockProvider

    monkeypatch.setattr(get_settings(), "bedrock_region", "ap-southeast-1")
    provider = BedrockProvider()
    assert isinstance(provider.client, AsyncAnthropicBedrockMantle)
    assert provider.model == "anthropic.claude-opus-5-5" and provider.effort == "high"

    monkeypatch.setattr(get_settings(), "bedrock_model_id", "")
    with pytest.raises(LLMError, match="BEDROCK_MODEL_ID"):
        BedrockProvider()
