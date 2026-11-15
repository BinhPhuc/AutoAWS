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

        class _PlainMessages:  # client.messages: the non-beta endpoint (gateways)
            def stream(self, **params):
                outer.requests.append({**params, "_endpoint": "messages"})
                return _FakeStream(message)

        self.messages = _PlainMessages()


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


class _Flaky(_FakeClient):
    """Fails `failures` times with an error event inside a 200 stream, then answers."""

    def __init__(self, failures: int, status: int = 200):
        import anthropic
        import httpx2

        super().__init__(_message([{"type": "text", "text": "ok"}]))
        request = httpx2.Request("POST", "https://gw.example/v1/messages")
        response = httpx2.Response(status, request=request)
        outer, ok_message = self, self.messages
        self.calls = 0

        class _Messages:
            def stream(self, **params):
                outer.calls += 1
                if outer.calls <= failures:
                    raise anthropic.APIStatusError(
                        "upstream error", response=response, body={"type": "api_error"}
                    )
                return ok_message.stream(**params)

        self.messages = _Messages()


@pytest.fixture
def no_backoff(monkeypatch):
    import app.llm.claude as claude

    async def instant(_seconds):
        return None

    monkeypatch.setattr(claude.asyncio, "sleep", instant)


async def test_an_error_inside_the_stream_is_retried(no_backoff):
    client = _Flaky(failures=2)
    provider = ClaudeMessagesProvider("anthropic", client, "m", "high", 100, claude_features=False)
    response = await provider.chat([LLMMessage(role="system", content="S")], [])
    assert response.text == "ok" and client.calls == 3


async def test_a_lasting_stream_error_is_reported_with_its_message(no_backoff):
    client = _Flaky(failures=5)
    provider = ClaudeMessagesProvider("anthropic", client, "m", "high", 100, claude_features=False)
    with pytest.raises(LLMError, match=r"API error 200 \(upstream error\)"):
        await provider.chat([LLMMessage(role="system", content="S")], [])
    assert client.calls == 3


async def test_client_errors_are_not_retried(no_backoff):
    client = _Flaky(failures=5, status=422)
    provider = ClaudeMessagesProvider("anthropic", client, "m", "high", 100, claude_features=False)
    with pytest.raises(LLMError):
        await provider.chat([LLMMessage(role="system", content="S")], [])
    assert client.calls == 1


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


async def test_a_gateway_gets_only_the_basic_request():
    """ANTHROPIC_BASE_URL (a Messages API gateway, possibly another model behind it): no
    Claude-only parameters, plain endpoint."""
    client = _FakeClient(_message([{"type": "text", "text": "{}"}]))
    provider = ClaudeMessagesProvider(
        "anthropic", client, "gemini-x", "high", 16000, claude_features=False
    )
    await provider.chat(
        [LLMMessage(role="system", content="SYS"), LLMMessage(role="user", content="Hỏi")],
        llm_tools(list_tools()),
    )
    [req] = client.requests
    assert req.pop("_endpoint") == "messages"
    assert set(req) == {"model", "max_tokens", "system", "messages", "tools"}
    assert req["model"] == "gemini-x"


def test_anthropic_provider_modes(monkeypatch):
    from app.config import get_settings
    from app.llm.anthropic import AnthropicProvider

    s = get_settings()
    # explicit: a developer's own .env may point at a gateway
    monkeypatch.setattr(s, "anthropic_base_url", "")
    monkeypatch.setattr(s, "anthropic_auth_token", "")
    monkeypatch.setattr(s, "anthropic_gateway_cache", False)
    monkeypatch.setattr(s, "anthropic_model", "claude-opus-5-5")
    monkeypatch.setattr(s, "anthropic_api_key", "sk-ant-test")
    direct = AnthropicProvider()
    assert direct.claude_features and direct.extra["fallbacks"] == "default"

    monkeypatch.setattr(s, "anthropic_api_key", "")
    monkeypatch.setattr(s, "anthropic_base_url", "https://gateway.example.com/")
    monkeypatch.setattr(s, "anthropic_auth_token", "sk-gateway-test")
    monkeypatch.setattr(s, "anthropic_model", "gemini-x")
    gw = AnthropicProvider()
    assert not gw.claude_features and gw.extra == {} and gw.model == "gemini-x"
    assert gw.gateway_cache is False
    assert str(gw.client.base_url).rstrip("/") == "https://gateway.example.com"
    assert gw.client.auth_headers == {"Authorization": "Bearer sk-gateway-test"}

    monkeypatch.setattr(s, "anthropic_gateway_cache", True)
    assert AnthropicProvider().gateway_cache is True

    monkeypatch.setattr(s, "anthropic_auth_token", "")
    with pytest.raises(LLMError, match="ANTHROPIC_AUTH_TOKEN"):
        AnthropicProvider()


async def test_gateway_cache_marks_the_repeated_prefix():
    """ANTHROPIC_GATEWAY_CACHE: explicit breakpoints on the system prompt, the last tool and
    the latest message, so every round after the first reads the prefix from the cache."""
    client = _FakeClient(_message([{"type": "text", "text": "{}"}]))
    provider = ClaudeMessagesProvider(
        "anthropic", client, "gemini-x", "high", 16000, claude_features=False, gateway_cache=True
    )
    messages = [
        LLMMessage(role="system", content="SYS"),
        LLMMessage(role="user", content="Hỏi"),
        LLMMessage(
            role="assistant",
            tool_calls=[ToolCallRequest(id="t1", name="describe_instances", input={})],
        ),
        LLMMessage(role="tool", tool_call_id="t1", tool_name="describe_instances", content="{}"),
    ]
    await provider.chat(messages, llm_tools(list_tools()))
    [req] = client.requests
    mark = {"type": "ephemeral"}
    assert req["system"] == [{"type": "text", "text": "SYS", "cache_control": mark}]
    assert req["tools"][-1]["cache_control"] == mark
    assert all("cache_control" not in t for t in req["tools"][:-1])
    assert req["messages"][-1]["content"][-1]["cache_control"] == mark  # the tool result
    assert "cache_control" not in req["messages"][0]["content"][-1]
    assert "cache_control" not in req  # no top-level form, no Claude-only parameters
    assert "thinking" not in req and "output_config" not in req


def test_cache_breakpoints_do_not_change_the_original_request():
    from app.llm.claude import with_cache_breakpoints

    req = {
        "system": "SYS",
        "tools": [{"name": "a"}, {"name": "b"}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "q"}]}],
    }
    marked = with_cache_breakpoints(req)
    assert req == {
        "system": "SYS",
        "tools": [{"name": "a"}, {"name": "b"}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "q"}]}],
    }
    assert marked["tools"][0] == {"name": "a"}
    # nothing to mark: stays as it was
    assert with_cache_breakpoints({"system": "", "tools": [], "messages": []}) == {
        "system": "",
        "tools": [],
        "messages": [],
    }


async def test_a_gateway_bot_challenge_is_reported_plainly():
    """A Cloudflare "Just a moment..." page (cloud IPs blocked) is not "no access to model"."""
    import anthropic
    import httpx2

    page = "<!DOCTYPE html><html><head><title>Just a moment...</title>" + "x" * 5000

    class Blocked(_FakeClient):
        def __init__(self):
            super().__init__(None)
            request = httpx2.Request("POST", "https://gw.example/v1/messages")
            response = httpx2.Response(403, request=request)

            class _Messages:
                def stream(self, **params):
                    raise anthropic.PermissionDeniedError(page, response=response, body=None)

            self.messages = _Messages()

    provider = ClaudeMessagesProvider(
        "anthropic", Blocked(), "m", "high", 100, claude_features=False
    )
    with pytest.raises(LLMError) as err:
        await provider.chat([LLMMessage(role="system", content="S")], [])
    assert "Cloudflare challenge" in str(err.value) and "<html" not in str(err.value)
