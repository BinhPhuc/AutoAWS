"""End-to-end chat with MockProvider: SSE event sequence + persistence."""

import json


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
    assert answer["answer"]["evidence"]
    assert any(e["source"] == "describe_instances" for e in answer["answer"]["evidence"])

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
