"""Chat Completions protocol and agent integration without a live model server."""

import json
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr

from app.aws.registry import REGISTRY, list_tools
from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMMessage
from app.llm.factory import get_provider
from app.llm.openai_compatible import OpenAICompatibleProvider
from tests.test_agent_loop import _stream


@pytest.fixture
def configured(monkeypatch):
    settings = get_settings()
    for key, value in {
        "llm_provider": "openai",
        "openai_base_url": "http://ollama.test:11434/v1/",
        "openai_model": "local-tool-model",
        "openai_api_key": SecretStr(""),
        "openai_timeout_seconds": 120,
        "openai_max_tokens": 4096,
        "openai_token_limit_field": "max_tokens",
        "agent_demo_mode": True,
        "max_agent_iterations": 10,
    }.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def completion(text=None, calls=None, reason="stop"):
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text, "tool_calls": calls},
                "finish_reason": reason,
            }
        ]
    }


def tool_call(call_id="call-1", arguments="{}", name="demo_instance_status"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


async def test_tool_round_trip(configured):
    requests = []
    tools = list_tools()

    def handle(request):
        assert request.url == "http://ollama.test:11434/v1/chat/completions"
        assert "authorization" not in request.headers
        assert request.extensions["timeout"]["read"] == 120
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == "local-tool-model"
        assert payload["max_tokens"] == 4096
        assert payload["stream"] is False
        assert payload["tool_choice"] == "auto"
        assert payload["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=completion("Đang kiểm tra", [tool_call(), tool_call("call-2")], "tool_calls"),
            )
        assert payload["messages"] == [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant",
                "content": "Đang kiểm tra",
                "tool_calls": [tool_call(), tool_call("call-2")],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": '{"state":"stopped"}'},
            {"role": "tool", "tool_call_id": "call-2", "content": '{"state":"stopped"}'},
        ]
        return httpx.Response(200, json=completion("Đã kiểm tra mô phỏng."))

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handle))
    messages = [LLMMessage(role="system", content="System"), LLMMessage(role="user", content="Hi")]
    first = await provider.chat(messages, tools)
    assert first.wants_tools and first.stop_reason == "tool_use"
    messages.append(LLMMessage(role="assistant", content=first.text, tool_calls=first.tool_calls))
    for call in first.tool_calls:
        messages.append(
            LLMMessage(role="tool", tool_call_id=call.id, content='{"state":"stopped"}')
        )
    assert (await provider.chat(messages, tools)).text == "Đã kiểm tra mô phỏng."
    assert len(requests) == 2


async def test_authenticated_text_chat_and_modern_token_limit(configured, monkeypatch):
    monkeypatch.setattr(configured, "openai_api_key", SecretStr("test-private-key"))
    monkeypatch.setattr(configured, "openai_token_limit_field", "max_completion_tokens")
    assert "test-private-key" not in repr(configured)

    def handle(request):
        assert request.headers["authorization"] == "Bearer test-private-key"
        body = json.loads(request.content)
        assert body["max_completion_tokens"] == 4096
        assert "max_tokens" not in body
        assert "tools" not in body and "tool_choice" not in body
        return httpx.Response(200, json=completion("Xin chào"))

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handle))
    result = await provider.chat([LLMMessage(role="user", content="Hi")], [])
    assert result.text == "Xin chào"
    assert not result.wants_tools


@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500, 503])
async def test_http_errors_do_not_expose_payloads(configured, status):
    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                json={"error": "sensitive-user-input-and-key"},
                headers={"location": "/other"},
            )
        )
    )
    with pytest.raises(LLMError, match=f"HTTP {status}") as error:
        await provider.chat([LLMMessage(role="user", content="Hi")], [])
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
async def test_network_failure_is_safe(configured, failure):
    def handle(request):
        raise failure("private-network-detail", request=request)

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handle))
    with pytest.raises(LLMError) as error:
        await provider.chat([LLMMessage(role="user", content="Hi")], [])
    assert "private-network-detail" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"choices": []},
        completion("partial", reason="length"),
        completion("blocked", reason="content_filter"),
        completion("bad reason", reason={}),
        completion(""),
        completion(calls=[], reason="tool_calls"),
        completion(calls=[tool_call(arguments="invalid-private-arguments")], reason="tool_calls"),
        completion(calls=[tool_call(arguments="[]")], reason="tool_calls"),
        completion(calls=[tool_call(arguments="null")], reason="tool_calls"),
        completion(calls=[tool_call(call_id="")], reason="tool_calls"),
        completion(calls=[tool_call(name="")], reason="tool_calls"),
        completion(calls=[tool_call(), tool_call()], reason="tool_calls"),
        completion(calls=[tool_call(), {"id": "malformed"}], reason="tool_calls"),
        completion(calls={"invalid": True}, reason="tool_calls"),
        completion(text={"invalid": True}),
    ],
)
async def test_malformed_or_incomplete_response_rejected(configured, payload):
    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    with pytest.raises(LLMError) as error:
        await provider.chat([LLMMessage(role="user", content="Hi")], [])
    assert "private-arguments" not in str(error.value)


async def test_non_json_response(configured):
    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="private-html"))
    )
    with pytest.raises(LLMError, match="invalid JSON"):
        await provider.chat([LLMMessage(role="user", content="Hi")], [])


@pytest.mark.parametrize(
    "url", ["", "ftp://server/v1", "http://user:private@server/v1", "http://server/v1?key=private"]
)
async def test_invalid_url_rejected(configured, monkeypatch, url):
    monkeypatch.setattr(configured, "openai_base_url", url)
    with pytest.raises(LLMError, match="OPENAI_BASE_URL") as error:
        await OpenAICompatibleProvider().chat([], [])
    assert "private" not in str(error.value)


async def test_missing_model_and_tool_call_id(configured, monkeypatch):
    monkeypatch.setattr(configured, "openai_model", "")
    with pytest.raises(LLMError, match="OPENAI_MODEL"):
        await get_provider().chat([], [])
    monkeypatch.setattr(configured, "openai_model", "test")
    with pytest.raises(LLMError, match="tool_call_id"):
        await get_provider().chat([LLMMessage(role="tool", content="{}")], [])


def test_openai_settings_loaded_from_dotenv(tmp_path, monkeypatch):
    for key in ("LLM_PROVIDER", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "LLM_PROVIDER=openai\nOPENAI_BASE_URL=http://model-server:11434/v1\n"
        "OPENAI_MODEL=local-model\nOPENAI_API_KEY=test-env-key\n"
    )
    settings = Settings(_env_file=env)
    assert settings.llm_provider == "openai"
    assert settings.openai_base_url == "http://model-server:11434/v1"
    assert settings.openai_model == "local-model"
    assert settings.openai_api_key.get_secret_value() == "test-env-key"
    assert "test-env-key" not in repr(settings)


@pytest.mark.parametrize("mode", ["answer", "limit", "unknown", "unavailable"])
def test_agent_sse(client, connection, configured, monkeypatch, mode):
    requests = []
    spec = list_tools()[0]
    executions = []

    def run(session, params):
        executions.append(params)
        return {"simulated": True, "state": "stopped", "password": "private-test-value"}

    monkeypatch.setitem(REGISTRY, spec.name, replace(spec, fn=run))
    answer = {
        "summary": "Instance mô phỏng đang dừng.",
        "cause": "Kết quả mô phỏng trả stopped.",
        "evidence": [{"text": "Fixture trả stopped.", "source": spec.name, "verified": True}],
        "fix_steps": [],
        "unverified": [
            {"text": "Chưa kiểm tra AWS thật.", "how_to_check": "Kiểm tra EC2 console."}
        ],
        "confidence": "low",
    }

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if mode == "unavailable":
            return httpx.Response(503, text="private-error")
        if len(requests) == 1 or mode == "limit":
            name = "delete_everything" if mode == "unknown" else spec.name
            return httpx.Response(
                200,
                json=completion(
                    calls=[tool_call(str(len(requests)), name=name)], reason="tool_calls"
                ),
            )
        result_message = payload["messages"][-1]
        assert result_message["role"] == "tool" and result_message["tool_call_id"] == "1"
        result = json.loads(result_message["content"])
        if mode == "unknown":
            assert result.get("error")
        else:
            assert result["password"] == "[REDACTED]"
            assert "private-test-value" not in request.content.decode()
        return httpx.Response(200, json=completion(json.dumps(answer, ensure_ascii=False)))

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handle))
    assert isinstance(get_provider(), OpenAICompatibleProvider)
    monkeypatch.setattr("app.api.conversations.get_provider", lambda: provider)
    conv_id = client.post("/api/conversations", json={"connection_id": connection["id"]}).json()[
        "data"
    ]["id"]
    events = _stream(client, conv_id, "Kiểm tra trạng thái instance demo")
    assert events[-1][0] == "done"
    if mode in {"limit", "unavailable"}:
        assert events[-2][0] == "error"
        assert events[-2][1]["error"] == (
            "MAX_ITERATIONS" if mode == "limit" else "LLM_UNAVAILABLE"
        )
        assert len(requests) == (10 if mode == "limit" else 1)
    else:
        assert len(requests) == 2
        assert [t for t, _ in events].count("tool_call") == 1
        assert events[-2][0] == "answer"
        saved = client.get(f"/api/conversations/{conv_id}").json()["data"]["messages"][-1]
        assert saved["answer"] == answer
        assert len(saved["tool_calls"]) == 1
        assert saved["tool_calls"][0]["status"] == ("error" if mode == "unknown" else "ok")
    assert len(executions) == {"answer": 1, "unknown": 0, "limit": 10, "unavailable": 0}[mode]
