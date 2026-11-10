"""LLM_PROVIDER=mcp: an MCP client answers the agent loop's turns."""

import asyncio
import json

import pytest
from mcp.client.client import Client

from app.agent.loop import run_agent
from app.aws.registry import list_tools
from app.llm.base import LLMError, LLMMessage
from app.llm.mcp_bridge import LLMBridge, McpBridgeProvider, ToolCallIn, bridge, build_mcp_server
from app.storage.models import Conversation

MESSAGES = [
    LLMMessage(role="system", content="SYS"),
    LLMMessage(role="user", content="Không SSH được vào web-server"),
]


def _json(result) -> dict:
    return json.loads(result.content[0].text)


async def test_round_trip_tool_calls_then_final_text():
    b = LLMBridge()
    tools = list_tools()

    task = asyncio.create_task(b.submit(MESSAGES, tools, timeout=5))
    turn = await b.next_request(wait_seconds=2)
    assert turn is not None
    assert turn.last_user_message() == "Không SSH được vào web-server"
    b.respond(
        turn.request_id, None, [ToolCallIn(name="describe_instances", input={"name_tag": "web"})]
    )
    resp = await task
    assert resp.wants_tools
    [call] = resp.tool_calls
    assert (call.name, call.input) == ("describe_instances", {"name_tag": "web"})
    assert call.id == f"{turn.request_id}_1"
    assert await b.next_request(wait_seconds=0) is None  # answered turns leave the queue

    task = asyncio.create_task(b.submit(MESSAGES, tools, timeout=5))
    turn = await b.next_request(wait_seconds=2)
    b.respond(turn.request_id, '{"summary": "s", "cause": "c"}', None)
    resp = await task
    assert not resp.wants_tools
    assert resp.text == '{"summary": "s", "cause": "c"}'


async def test_bad_answers_are_rejected_and_the_turn_stays_open():
    b = LLMBridge()
    task = asyncio.create_task(b.submit(MESSAGES, list_tools(), timeout=5))
    turn = await b.next_request(wait_seconds=2)

    with pytest.raises(ValueError, match="Unknown tool 'rm_rf'"):
        b.respond(turn.request_id, None, [ToolCallIn(name="rm_rf")])
    with pytest.raises(ValueError, match="exactly one"):
        b.respond(turn.request_id, "x", [ToolCallIn(name="describe_instances")])
    with pytest.raises(ValueError, match="exactly one"):
        b.respond(turn.request_id, None, None)
    with pytest.raises(ValueError, match="No pending request"):
        b.respond("llm_nope", "x", None)

    b.respond(turn.request_id, "done", None)
    await task
    with pytest.raises(ValueError, match="No pending request"):
        b.respond(turn.request_id, "again", None)


async def test_timeout_becomes_llm_error():
    b = LLMBridge()
    with pytest.raises(LLMError, match="no MCP client answered"):
        await b.submit(MESSAGES, [], timeout=0.05)
    assert b.pending() == []


async def test_cancelled_turn_leaves_the_queue():
    b = LLMBridge()
    task = asyncio.create_task(b.submit(MESSAGES, [], timeout=5))
    await asyncio.sleep(0)
    assert len(b.pending()) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert b.pending() == []


async def test_mcp_tools():
    b = LLMBridge()
    async with Client(build_mcp_server(b)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names == {"next_llm_request", "respond_llm_request", "list_llm_requests"}
        assert _json(await client.call_tool("next_llm_request", {"wait_seconds": 0})) == {
            "pending": False
        }

        task = asyncio.create_task(b.submit(MESSAGES, list_tools(), timeout=5))
        got = _json(await client.call_tool("next_llm_request", {"wait_seconds": 2}))
        assert got["pending"] is True
        assert got["system"] == "SYS"
        assert got["messages"] == [{"role": "user", "content": "Không SSH được vào web-server"}]
        assert any(t["name"] == "describe_route_tables" for t in got["tools"])

        lean = _json(
            await client.call_tool(
                "next_llm_request", {"include_system": False, "include_tools": False}
            )
        )
        assert "system" not in lean and "tools" not in lean

        listed = await client.call_tool("list_llm_requests", {})
        assert [r["request_id"] for r in _json(listed)["requests"]] == [got["request_id"]]

        bad = await client.call_tool(
            "respond_llm_request",
            {"request_id": got["request_id"], "tool_calls": [{"name": "nope", "input": {}}]},
        )
        assert bad.is_error
        assert "Unknown tool 'nope'" in bad.content[0].text  # the reason reaches the client

        ok = await client.call_tool(
            "respond_llm_request",
            {
                "request_id": got["request_id"],
                "tool_calls": [{"name": "describe_route_tables", "input": {"vpc_id": "vpc-1"}}],
            },
        )
        assert not ok.is_error
        resp = await task
        assert resp.tool_calls[0].input == {"vpc_id": "vpc-1"}

        # The final answer is JSON sent as a string: it must arrive as text, not a dict.
        task = asyncio.create_task(b.submit(MESSAGES, list_tools(), timeout=5))
        got = _json(await client.call_tool("next_llm_request", {"include_tools": False}))
        answer = json.dumps({"summary": "Đã rõ", "cause": "c"}, ensure_ascii=False)
        ok = await client.call_tool(
            "respond_llm_request", {"request_id": got["request_id"], "text": answer}
        )
        assert not ok.is_error, ok.content[0].text
        assert (await task).text == answer


async def test_agent_turn_driven_through_the_bridge(store, aws):
    """Full turn: agent asks the MCP client, runs the chosen tool on moto, gets JSON back."""
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)

    def final(subnet_id: str) -> dict:
        return {
            "summary": "Instance đang chạy.",
            "root_causes": [
                {
                    "statement": "Không có lỗi cấu hình.",
                    "confidence": "medium",
                    "evidence": [
                        {
                            "text": "1 instance running",
                            "source": "describe_instances",
                            "resource_id": subnet_id,
                        }
                    ],
                }
            ],
            "fix_steps": [],
            "unverified": [],
            "confidence": "medium",
        }

    async def play_the_llm():
        turn = await bridge.next_request(wait_seconds=5)
        payload = turn.to_payload()
        names = {t["name"] for t in payload["tools"]}
        assert "submit_diagnosis" in names
        described = next(t for t in payload["tools"] if t["name"] == "describe_instances")
        assert "refresh" in described["input_schema"]["properties"]
        bridge.respond(turn.request_id, None, [ToolCallIn(name="describe_instances")])
        turn = await bridge.next_request(wait_seconds=5)
        tool_msg = turn.messages[-1]
        assert tool_msg.role == "tool" and tool_msg.tool_name == "describe_instances"
        assert json.loads(tool_msg.content)["instances"][0]["subnet_id"] == subnet
        bridge.respond(
            turn.request_id, None, [ToolCallIn(name="submit_diagnosis", input=final(subnet))]
        )

    conv = store.create_conversation(Conversation(connection_id="conn_bridge"))
    llm = asyncio.create_task(play_the_llm())
    events = [
        e async for e in run_agent(store, conv, "Kiểm tra instance", aws, McpBridgeProvider())
    ]
    await llm

    types = [e.type for e in events]
    assert "tool_call" in types and types[-2:] == ["answer", "done"]
    calls = [e.data["tool"] for e in events if e.type == "tool_call"]
    assert calls == ["describe_instances"]  # submit_diagnosis is not a timeline entry
    answer = next(e for e in events if e.type == "answer")
    assert answer.data["answer"]["confidence"] == "medium"
    [evidence] = answer.data["answer"]["root_causes"][0]["evidence"]
    assert evidence["verification"] == "read"
    [user, assistant] = store.list_messages(conv.id)
    assert (user.role, assistant.role) == ("user", "assistant")
    assert [t.tool for t in store.list_tool_calls(assistant.id)] == ["describe_instances"]
