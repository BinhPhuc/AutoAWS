"""End-to-end chat with MockProvider: SSE event sequence + persistence."""

import json

import pytest


def _stream(client, conv_id, content):
    events = []
    with client.stream(
        "POST", f"/api/conversations/{conv_id}/messages", json={"content": content}
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        event = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event:
                events.append((event, json.loads(line.split(":", 1)[1].strip())))
                event = None
    return events


def test_chat_stream_and_persist(client, connection, aws):
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)

    conv = client.post("/api/conversations", json={"connection_id": connection["id"]})
    assert conv.status_code == 201
    conv_id = conv.json()["data"]["id"]

    events = _stream(client, conv_id, "I can't SSH into my instance, port 22 is open")
    types = [t for t, _ in events]
    assert types[0] == "status"
    assert "tool_call" in types and "tool_result" in types
    assert types[-2:] == ["answer", "done"]
    assert "error" not in types

    calls = [d for t, d in events if t == "tool_call"]
    assert {c["tool"] for c in calls} >= {"describe_instances", "describe_security_groups"}
    results = {d["id"]: d for t, d in events if t == "tool_result"}
    assert all(c["id"] in results for c in calls)

    answer = next(d for t, d in events if t == "answer")
    assert answer["answer"]["confidence"] == "low"
    evidence = answer["answer"]["root_causes"][0]["evidence"]
    instances = next(e for e in evidence if e["source"] == "describe_instances")
    # the mock cites the instance id it read; the server confirms it in the tool output
    assert instances["resource_id"].startswith("i-")
    assert instances["verification"] == "read" and instances["verified"] is True
    assert answer["answer"]["limit_reached"] is None
    assert "submit_diagnosis" not in {c["tool"] for c in calls}

    # persisted before `done`
    got = client.get(f"/api/conversations/{conv_id}").json()["data"]
    assert got["title"].startswith("I can't SSH")
    roles = [m["role"] for m in got["messages"]]
    assert roles == ["user", "assistant"]
    assistant = got["messages"][1]
    assert assistant["id"] == answer["message_id"]
    assert assistant["answer"]["summary"] == answer["content"]
    assert len(assistant["tool_calls"]) == len(calls)
    assert assistant["tool_calls"][0]["status"] in ("ok", "error")

    # follow-up question in the same conversation works and history is replayed
    events2 = _stream(client, conv_id, "What about the load balancer, we see 502 errors?")
    assert [t for t, _ in events2][-2:] == ["answer", "done"]
    got = client.get(f"/api/conversations/{conv_id}").json()["data"]
    assert len(got["messages"]) == 4


def test_message_on_unverified_connection(client):
    r = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "x",
            "region": "ap-southeast-1",
            "role_arn": "arn:aws:iam::123456789012:role/R",
        },
    )
    body = client.post("/api/conversations", json={"connection_id": r.json()["data"]["id"]}).json()
    assert body["error"] == "CONNECTION_NOT_VERIFIED"


def test_conversation_filters_and_delete(client, connection):
    conv_id = client.post("/api/conversations", json={"connection_id": connection["id"]}).json()[
        "data"
    ]["id"]
    listed = client.get(f"/api/conversations?connection_id={connection['id']}").json()["data"]
    assert conv_id in [c["id"] for c in listed]
    assert listed[0].get("messages") is None
    assert client.delete(f"/api/conversations/{conv_id}").json()["data"] is None
    assert client.get(f"/api/conversations/{conv_id}").json()["error"] == "CONVERSATION_NOT_FOUND"


# ---- turns that end without an answer are still stored ------------------------


class _FailingProvider:
    name = "failing"

    async def chat(self, messages, tools):
        from app.llm.base import LLMError

        raise LLMError("quota exceeded")


class _AlwaysToolsProvider:
    name = "always-tools"

    async def chat(self, messages, tools):
        from app.llm.base import LLMResponse, ToolCallRequest

        call = ToolCallRequest(id=f"tc{len(messages)}", name="get_caller_identity", input={})
        return LLMResponse(tool_calls=[call], stop_reason="tool_use")


class _BlockingProvider:
    """Never answers: lets a test cancel the turn while the LLM is 'thinking'."""

    name = "blocking"

    async def chat(self, messages, tools):
        import asyncio

        await asyncio.Event().wait()


def _new_conversation(client, connection) -> str:
    return client.post("/api/conversations", json={"connection_id": connection["id"]}).json()[
        "data"
    ]["id"]


def test_failed_turn_is_stored_with_a_note(client, connection, monkeypatch):
    from app.api import conversations as conversations_api

    monkeypatch.setattr(conversations_api, "get_provider", lambda: _FailingProvider())
    conv_id = _new_conversation(client, connection)
    events = _stream(client, conv_id, "Website báo 502")
    assert [t for t, _ in events][-2:] == ["error", "done"]
    assert next(d for t, d in events if t == "error")["error"] == "LLM_UNAVAILABLE"

    messages = client.get(f"/api/conversations/{conv_id}").json()["data"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["answer"] is None
    assert messages[1]["content"].startswith("Chưa hoàn thành chẩn đoán: LLM provider")


def test_max_iterations_turn_keeps_its_tool_calls(client, connection, monkeypatch):
    from app.api import conversations as conversations_api
    from app.config import get_settings

    monkeypatch.setattr(conversations_api, "get_provider", lambda: _AlwaysToolsProvider())
    monkeypatch.setattr(get_settings(), "max_agent_iterations", 3)
    conv_id = _new_conversation(client, connection)
    events = _stream(client, conv_id, "Kiểm tra giúp")
    assert next(d for t, d in events if t == "error")["error"] == "MAX_ITERATIONS"

    assistant = client.get(f"/api/conversations/{conv_id}").json()["data"]["messages"][1]
    assert assistant["answer"] is None
    assert "dừng sau 3 bước" in assistant["content"]
    assert [tc["tool"] for tc in assistant["tool_calls"]] == ["get_caller_identity"] * 3


async def test_turn_closed_by_the_client_is_stored(store, aws):
    """Client disconnects while the stream is suspended between events (aclose)."""
    from app.agent.loop import STOPPED_NOTE, run_agent
    from app.llm.mock import MockProvider
    from app.storage.models import Conversation

    conv = store.create_conversation(Conversation(connection_id="conn_x"))
    agen = run_agent(store, conv, "không ssh được", aws, MockProvider())
    assert (await agen.__anext__()).type == "status"
    await agen.aclose()
    msgs = store.list_messages(conv.id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].content == STOPPED_NOTE and msgs[1].answer_json is None


async def test_turn_cancelled_while_waiting_for_the_llm_is_stored(store, aws):
    """Stop pressed while the provider is working (sse-starlette cancels the task)."""
    import asyncio

    from app.agent.loop import STOPPED_NOTE, run_agent
    from app.storage.models import Conversation

    conv = store.create_conversation(Conversation(connection_id="conn_y"))

    async def consume():
        async for _ in run_agent(store, conv, "502", aws, _BlockingProvider()):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    msgs = store.list_messages(conv.id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].content == STOPPED_NOTE


async def test_second_question_sees_the_first_turn(store, aws):
    """Acceptance: on the 2nd question the LLM receives turn 1 (question, shortened tool
    results and answer) from storage — on both backends."""
    import json as _json

    from app.agent.loop import run_agent
    from app.llm.base import LLMResponse, ToolCallRequest
    from app.storage.models import Conversation

    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)
    answer1 = {
        "summary": "web-server đang chạy",
        "cause": "Route table thiếu 0.0.0.0/0",
        "evidence": [],
        "fix_steps": [],
        "unverified": [],
        "confidence": "high",
    }

    class Scripted:
        name = "scripted"

        def __init__(self):
            self.calls = []

        async def chat(self, messages, tools):
            self.calls.append(list(messages))
            if (
                not any(m.role == "tool" for m in messages[len(messages) - 3 :])
                and len(self.calls) == 1
            ):
                call = ToolCallRequest(id="t1", name="describe_instances", input={})
                return LLMResponse(tool_calls=[call], stop_reason="tool_use")
            return LLMResponse(text=_json.dumps(answer1, ensure_ascii=False))

    conv = store.create_conversation(Conversation(connection_id="conn_hist"))
    turn1 = Scripted()
    [e async for e in run_agent(store, conv, "Không SSH được vào web-server", aws, turn1)]
    turn2 = Scripted()
    turn2.calls.append([])  # skip the tool-call branch: answer directly
    [e async for e in run_agent(store, conv, "Vậy sửa thế nào?", aws, turn2)]

    seen = turn2.calls[1]  # what the LLM received on the 2nd question
    roles = [m.role for m in seen]
    assert roles == ["system", "user", "assistant", "user"]
    assert seen[1].content == "Không SSH được vào web-server"
    replay = seen[2].content
    assert "[Data read earlier]" in replay
    assert "- describe_instances {}: 1 instances" in replay  # shortened result, not raw data
    assert "Route table thiếu 0.0.0.0/0" in replay  # the turn-1 answer
    assert seen[3].content.startswith("[Context]")
    assert seen[3].content.endswith("[Question]\nVậy sửa thế nào?")
    assert len(store.list_messages(conv.id)) == 4
    # the turn-1 answer was stored in the old shape and is read back in the new one
    stored = store.list_messages(conv.id)[1].answer_json
    assert '"root_causes"' in stored and "Route table thiếu" in stored
