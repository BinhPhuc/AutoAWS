"""Converse wire format and full API demo tests without live AWS credentials."""

import json
from dataclasses import replace

import pytest
from botocore.stub import Stubber
from pydantic import ValidationError

from app.aws.registry import REGISTRY, list_tools, run_tool
from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMMessage
from app.llm.bedrock import BedrockProvider
from tests.test_agent_loop import _stream


@pytest.fixture
def demo(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_demo_mode", True)
    monkeypatch.setattr(settings, "bedrock_model_id", "test-model")
    monkeypatch.setattr(settings, "bedrock_region", "ap-southeast-1")
    monkeypatch.setattr(settings, "llm_provider", "bedrock")
    return settings


def response(blocks, reason="end_turn"):
    return {
        "output": {"message": {"role": "assistant", "content": blocks}},
        "stopReason": reason,
        "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
        "metrics": {"latencyMs": 1},
    }


def tool_use(call_id="call-1"):
    return {"toolUse": {"toolUseId": call_id, "name": "demo_instance_status", "input": {}}}


@pytest.mark.asyncio
async def test_converse_wire_format(demo, aws, monkeypatch):
    client = aws.client("bedrock-runtime")
    monkeypatch.setattr("app.aws.bedrock.platform_session", lambda: aws)
    monkeypatch.setattr(aws, "client", lambda *a, **kw: client)
    provider = BedrockProvider()
    tools = list_tools()
    messages = [LLMMessage(role="system", content="System"), LLMMessage(role="user", content="Hi")]
    expected = {
        "modelId": "test-model",
        "system": [{"text": "System"}],
        "messages": [{"role": "user", "content": [{"text": "Hi"}]}],
        "inferenceConfig": {"maxTokens": 2048},
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": {"json": t.input_schema},
                    }
                }
                for t in tools
            ]
        },
    }
    with Stubber(client) as stub:
        stub.add_response(
            "converse", response([tool_use(), tool_use("call-2")], "tool_use"), expected
        )
        first = await provider.chat(messages, tools)
        messages.append(LLMMessage(role="assistant", tool_calls=first.tool_calls))
        for call in first.tool_calls:
            messages.append(
                LLMMessage(role="tool", tool_call_id=call.id, content='{"state":"stopped"}')
            )
        expected["messages"] += [
            {"role": "assistant", "content": [tool_use(), tool_use("call-2")]},
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": call.id,
                            "content": [{"json": {"state": "stopped"}}],
                            "status": "success",
                        }
                    }
                    for call in first.tool_calls
                ],
            },
        ]
        stub.add_response("converse", response([{"text": "Đã kiểm tra mô phỏng."}]), expected)
        assert (await provider.chat(messages, tools)).text == "Đã kiểm tra mô phỏng."
        stub.assert_no_pending_responses()


def test_demo_sse(client, connection, demo, monkeypatch):
    calls = []
    spec = list_tools()[0]
    monkeypatch.setitem(
        REGISTRY,
        spec.name,
        replace(
            spec,
            fn=lambda session, params: {
                "simulated": True,
                "state": "stopped",
                "password": "private-test-value",
            },
        ),
    )
    answer = {
        "summary": "Dữ liệu mô phỏng: instance đang dừng.",
        "cause": "Instance mô phỏng ở trạng thái stopped.",
        "evidence": [
            {"text": "Fixture trả stopped.", "source": "demo_instance_status", "verified": True}
        ],
        "fix_steps": [],
        "unverified": [
            {"text": "Trạng thái AWS thật chưa xác nhận.", "how_to_check": "Check the EC2 console."}
        ],
        "confidence": "low",
    }

    def converse(region, request):
        calls.append(request)
        if len(calls) == 1:
            return response([tool_use()], "tool_use")
        result = request["messages"][-1]["content"][0]["toolResult"]
        assert result["toolUseId"] == "call-1"
        assert result["content"][0]["json"]["simulated"] is True
        assert result["content"][0]["json"]["password"] == "[REDACTED]"
        return response([{"text": json.dumps(answer)}])

    monkeypatch.setattr("app.llm.bedrock.converse", converse)
    conv_id = client.post("/api/conversations", json={"connection_id": connection["id"]}).json()[
        "data"
    ]["id"]
    events = _stream(client, conv_id, "Kiểm tra instance demo")
    assert [t for t, _ in events].count("tool_call") == 1
    assert [t for t, _ in events][-2:] == ["answer", "done"]
    assert len(calls) == 2
    saved = client.get(f"/api/conversations/{conv_id}").json()["data"]["messages"][-1]
    assert saved["answer"] == answer
    assert len(saved["tool_calls"]) == 1
    assert [t["name"] for t in client.get("/api/tools").json()["data"]] == ["demo_instance_status"]


def test_iteration_limit(client, connection, demo, monkeypatch):
    count = 0

    def converse(*args):
        nonlocal count
        count += 1
        return response([tool_use(str(count))], "tool_use")

    monkeypatch.setattr("app.llm.bedrock.converse", converse)
    conv_id = client.post("/api/conversations", json={"connection_id": connection["id"]}).json()[
        "data"
    ]["id"]
    events = _stream(client, conv_id, "Demo")
    assert count == 10
    assert [t for t, _ in events][-2:] == ["error", "done"]
    assert events[-2][1]["error"] == "MAX_ITERATIONS"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,blocks", [("max_tokens", [{"text": "partial"}]), ("end_turn", [])])
async def test_incomplete_response(demo, monkeypatch, reason, blocks):
    monkeypatch.setattr("app.llm.bedrock.converse", lambda *args: response(blocks, reason))
    with pytest.raises(LLMError):
        await BedrockProvider().chat([LLMMessage(role="user", content="Hi")], list_tools())


def test_demo_allowlist(demo, aws, monkeypatch):
    assert run_tool(aws, "describe_instances", {}).status == "error"
    assert run_tool(aws, "demo_instance_status", {}).output["simulated"] is True
    monkeypatch.setattr(demo, "agent_demo_mode", False)
    assert "demo_instance_status" not in {t.name for t in list_tools()}
    assert run_tool(aws, "demo_instance_status", {}).status == "error"


@pytest.mark.parametrize("limit", [0, 11])
def test_invalid_limit(limit):
    with pytest.raises(ValidationError):
        Settings(max_agent_iterations=limit)


@pytest.mark.asyncio
async def test_bedrock_access_denied(demo, aws, monkeypatch):
    client = aws.client("bedrock-runtime")
    monkeypatch.setattr("app.aws.bedrock.platform_session", lambda: aws)
    monkeypatch.setattr(aws, "client", lambda *a, **kw: client)
    with Stubber(client) as stub:
        stub.add_client_error(
            "converse",
            service_error_code="AccessDeniedException",
            service_message="sensitive service detail",
        )
        with pytest.raises(LLMError, match="Bedrock request failed") as exc:
            await BedrockProvider().chat([LLMMessage(role="user", content="Hi")], list_tools())
        assert "sensitive" not in str(exc.value)


@pytest.mark.asyncio
async def test_missing_credentials(demo, monkeypatch):
    from botocore.exceptions import NoCredentialsError

    def missing_session():
        raise NoCredentialsError()

    monkeypatch.setattr("app.aws.bedrock.platform_session", missing_session)
    with pytest.raises(LLMError, match="NoCredentialsError"):
        await BedrockProvider().chat([LLMMessage(role="user", content="Hi")], list_tools())


def test_json_retry_uses_iteration_budget(client, connection, demo, monkeypatch):
    monkeypatch.setattr(demo, "max_agent_iterations", 1)
    calls = []

    def converse(*args):
        calls.append(args)
        return response([{"text": "Not JSON"}])

    monkeypatch.setattr("app.llm.bedrock.converse", converse)
    conv_id = client.post("/api/conversations", json={"connection_id": connection["id"]}).json()[
        "data"
    ]["id"]
    events = _stream(client, conv_id, "Demo")
    assert len(calls) == 1
    assert events[-2][1]["error"] == "MAX_ITERATIONS"
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_account_restriction_is_actionable_without_exposing_service_payload(
    demo, aws, monkeypatch, caplog
):
    client = aws.client("bedrock-runtime")
    monkeypatch.setattr("app.aws.bedrock.platform_session", lambda: aws)
    monkeypatch.setattr(aws, "client", lambda *a, **kw: client)
    with Stubber(client) as stub:
        stub.add_client_error(
            "converse",
            service_error_code="ValidationException",
            service_message="Operation not allowed",
            response_meta={"RequestId": "test-bedrock-request"},
        )
        with pytest.raises(LLMError, match="Bedrock inference is blocked for this AWS account"):
            await BedrockProvider().chat([LLMMessage(role="user", content="Hi")], list_tools())
    assert "test-bedrock-request" in caplog.text


@pytest.mark.asyncio
async def test_other_validation_messages_are_not_echoed(demo, aws, monkeypatch):
    client = aws.client("bedrock-runtime")
    monkeypatch.setattr("app.aws.bedrock.platform_session", lambda: aws)
    monkeypatch.setattr(aws, "client", lambda *a, **kw: client)
    with Stubber(client) as stub:
        stub.add_client_error(
            "converse",
            service_error_code="ValidationException",
            service_message="Request content contains private user input",
        )
        with pytest.raises(LLMError, match="ValidationException") as error:
            await BedrockProvider().chat([LLMMessage(role="user", content="Hi")], list_tools())
        assert "private user input" not in str(error.value)
