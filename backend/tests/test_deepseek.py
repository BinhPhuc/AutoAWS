"""Exercise the real SDK against a fake DeepSeek API, without credentials or billing."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.aws.registry import list_tools
from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMMessage
from app.llm.deepseek import DeepSeekProvider
from app.llm.factory import get_provider
from tests.test_openai_compatible import completion, tool_call


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = get_settings()
    for key, value in {
        "llm_provider": "deepseek",
        "deepseek_api_key": SecretStr("deepseek-test-key"),
        "deepseek_model": "deepseek-flash",
        "deepseek_timeout_seconds": 37,
        "deepseek_max_tokens": 2048,
        "deepseek_thinking": False,
        "openai_base_url": "https://unused-gateway.test/v1",
        "openai_api_key": SecretStr("unused-gateway-key"),
    }.items():
        monkeypatch.setattr(settings, key, value)
    return settings


@pytest.mark.parametrize("thinking", [False, True])
async def test_sdk_tool_round_trip(
    configured: Settings, monkeypatch: pytest.MonkeyPatch, thinking: bool
) -> None:
    monkeypatch.setattr(configured, "deepseek_thinking", thinking)
    assert isinstance(get_provider(), DeepSeekProvider)
    requests = []
    tools = list_tools()

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer deepseek-test-key"
        assert request.extensions["timeout"]["read"] == 37
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == "deepseek-flash"
        assert payload["max_tokens"] == 2048
        assert payload["stream"] is False
        assert payload["thinking"] == {"type": "enabled" if thinking else "disabled"}
        assert payload["tool_choice"] == "auto"
        assert {t["function"]["name"] for t in payload["tools"]} == {t.name for t in tools}
        if len(requests) == 1:
            response = completion(calls=[tool_call(name="describe_instances")], reason="tool_calls")
            if thinking:
                response["choices"][0]["message"]["reasoning_content"] = "private-reasoning"
        else:
            assistant = payload["messages"][-2]
            if thinking:
                assert assistant["reasoning_content"] == "private-reasoning"
            else:
                assert "reasoning_content" not in assistant
            assert payload["messages"][-1] == {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": '{"state":"stopped"}',
            }
            response = completion("Instance đang dừng.")
        response["usage"] = {"prompt_tokens": 123, "completion_tokens": 45}
        return httpx.Response(200, json=response)

    provider = DeepSeekProvider(transport=httpx.MockTransport(handle))
    messages = [LLMMessage(role="user", content="Kiểm tra EC2")]
    first = await provider.chat(messages, tools)
    assert first.wants_tools and first.tool_calls[0].name == "describe_instances"
    assert first.text is None
    assert (first.input_tokens, first.output_tokens) == (123, 45)
    messages.extend(
        [
            LLMMessage(role="assistant", tool_calls=first.tool_calls, raw=first.raw),
            LLMMessage(role="tool", tool_call_id="call-1", content='{"state":"stopped"}'),
        ]
    )
    assert (await provider.chat(messages, tools)).text == "Instance đang dừng."


@pytest.mark.parametrize("status", [302, 400, 401, 402, 403, 404, 422, 429, 500, 503])
async def test_http_errors_are_safe_and_not_retried(configured: Settings, status: int) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": {"message": "private-key-and-user-data"}},
            headers={"location": "https://other.test"},
        )

    provider = DeepSeekProvider(transport=httpx.MockTransport(handle))
    with pytest.raises(LLMError, match=f"DeepSeek.*HTTP {status}") as error:
        await provider.chat([LLMMessage(role="user", content="Hi")], [])
    assert len(requests) == 1
    assert "private-key" not in str(error.value)
    if status == 402:
        assert "balance" in str(error.value)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
async def test_network_errors_are_safe(
    configured: Settings, failure: type[httpx.RequestError]
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise failure("private-network-details", request=request)

    provider = DeepSeekProvider(transport=httpx.MockTransport(handle))
    with pytest.raises(LLMError, match="DeepSeek") as error:
        await provider.chat([], [])
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"choices": []},
        completion("partial", reason="length"),
        completion("blocked", reason="content_filter"),
        completion(""),
        completion(calls=[tool_call(arguments="private-invalid-json")], reason="tool_calls"),
        completion(calls=[tool_call(arguments="[]")], reason="tool_calls"),
        completion(calls=[tool_call(), tool_call()], reason="tool_calls"),
    ],
)
async def test_invalid_response_is_rejected(configured: Settings, payload: Any) -> None:
    provider = DeepSeekProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    with pytest.raises(LLMError, match="DeepSeek") as error:
        await provider.chat([], [])
    assert "private" not in str(error.value)


async def test_non_json_response(configured: Settings) -> None:
    provider = DeepSeekProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="private-html"))
    )
    with pytest.raises(LLMError, match="DeepSeek returned an invalid"):
        await provider.chat([], [])


@pytest.mark.parametrize("field", ["deepseek_api_key", "deepseek_model"])
async def test_required_configuration(
    configured: Settings, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    value = SecretStr(" ") if field.endswith("key") else " "
    monkeypatch.setattr(configured, field, value)
    with pytest.raises(LLMError, match=field.upper()):
        await get_provider().chat([], [])


def test_settings_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names = [
        "LLM_PROVIDER",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_THINKING",
        "DEEPSEEK_TIMEOUT_SECONDS",
        "DEEPSEEK_MAX_TOKENS",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "LLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=private-test-key\n"
        "DEEPSEEK_MODEL=deepseek-v4-pro\nDEEPSEEK_THINKING=true\n"
        "DEEPSEEK_TIMEOUT_SECONDS=60\nDEEPSEEK_MAX_TOKENS=8192\n"
    )
    settings = Settings(_env_file=env)
    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_model == "deepseek-v4-pro"
    assert settings.deepseek_api_key.get_secret_value() == "private-test-key"
    assert "private-test-key" not in repr(settings)
    assert settings.deepseek_thinking
    assert settings.deepseek_timeout_seconds == 60
    assert settings.deepseek_max_tokens == 8192
