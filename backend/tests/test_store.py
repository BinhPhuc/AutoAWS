"""Store contract: SQLite and DynamoDB must behave the same (fixture `store` runs both)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.storage.dynamo import DynamoStore, ensure_table
from app.storage.models import Connection, Conversation, Message, ToolCallRecord
from app.storage.store import get_store
from tests.conftest import FAKE_KEY, FAKE_SECRET, REGION

# In the past (touch_conversation uses "now") and on a whole second (no microseconds).
T0 = datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)


def _conn(name: str, at: datetime) -> Connection:
    return Connection(
        name=name,
        type="role",
        region=REGION,
        role_arn="arn:aws:iam::1:role/R",
        external_id="ext",
        created_at=at,
    )


def test_connections_crud(store):
    old = store.create_connection(_conn("old", T0))
    new = store.create_connection(_conn("new", T0 + timedelta(microseconds=500)))

    # The SQLite test DB is shared by the whole test session: look only at our items.
    mine = [c.id for c in store.list_connections() if c.id in {old.id, new.id}]
    assert mine == [new.id, old.id]  # newest first
    got = store.get_connection(old.id)
    assert got.name == "old" and got.created_at == T0 and got.last_error is None
    assert store.get_connection("conn_missing") is None

    got.status, got.account_id, got.last_verified_at = "connected", "123456789012", T0
    store.save_connection(got)
    again = store.get_connection(old.id)
    assert (again.status, again.account_id, again.last_verified_at) == (
        "connected",
        "123456789012",
        T0,
    )


def test_conversations_order_filter_and_title(store):
    a = store.create_connection(_conn("a", T0))
    b = store.create_connection(_conn("b", T0))
    c1 = store.create_conversation(Conversation(connection_id=a.id, updated_at=T0))
    c2 = store.create_conversation(Conversation(connection_id=a.id, updated_at=T0))
    c3 = store.create_conversation(Conversation(connection_id=b.id, updated_at=T0))

    store.touch_conversation(c1, title="Không SSH được")
    store.touch_conversation(c1, title="ignored: title already set")
    assert store.get_conversation(c1.id).title == "Không SSH được"
    assert [c.id for c in store.list_conversations(a.id)][0] == c1.id  # most recently updated
    assert {c.id for c in store.list_conversations(a.id)} == {c1.id, c2.id}
    assert {c.id for c in store.list_conversations()} >= {c1.id, c2.id, c3.id}
    assert store.get_conversation("conv_missing") is None


def test_messages_and_tool_calls(store):
    conv = store.create_conversation(Conversation(connection_id="conn_1"))
    # Same second, with and without microseconds: order must still follow time.
    q = store.add_message(
        Message(conversation_id=conv.id, role="user", content="hỏi", created_at=T0)
    )
    calls = [
        ToolCallRecord(
            tool="describe_instances",
            input_json='{"name_tag": "web"}',
            output_summary="1 instances",
            duration_ms=12,
        ),
        ToolCallRecord(
            tool="describe_route_tables",
            output_summary="Error: x",
            status="error",
            error="AccessDenied: no",
            duration_ms=3,
        ),
    ]
    a = store.add_message(
        Message(
            conversation_id=conv.id,
            role="assistant",
            content="đáp",
            answer_json=json.dumps({"summary": "s"}),
            created_at=T0 + timedelta(microseconds=1),
        ),
        calls,
    )
    store.add_message(Message(conversation_id="conv_other", role="user", content="khác"))

    msgs = store.list_messages(conv.id)
    assert [(m.id, m.role, m.content) for m in msgs] == [
        (q.id, "user", "hỏi"),
        (a.id, "assistant", "đáp"),
    ]
    assert msgs[0].created_at == T0 and msgs[1].answer_json == '{"summary": "s"}'

    fresh = DynamoStore(store.client, store.table) if isinstance(store, DynamoStore) else store
    for s in (store, fresh):  # cached and uncached (ById index) paths
        tcs = s.list_tool_calls(a.id)
        assert [(t.seq, t.tool, t.status, t.duration_ms) for t in tcs] == [
            (0, "describe_instances", "ok", 12),
            (1, "describe_route_tables", "error", 3),
        ]
        assert tcs[0].input_json == '{"name_tag": "web"}' and tcs[1].error == "AccessDenied: no"
        assert s.list_tool_calls(q.id) == []


def test_tool_call_output_and_cache_fields_round_trip(store):
    conv = store.create_conversation(Conversation(connection_id="conn_cache"))
    read_at = T0 + timedelta(seconds=5)
    output = json.dumps({"instances": [{"instance_id": "i-0abc", "name": "web-server"}]})
    a = store.add_message(
        Message(conversation_id=conv.id, role="assistant", content="đáp"),
        [
            ToolCallRecord(tool="describe_instances", output_json=output, read_at=read_at),
            ToolCallRecord(tool="describe_instances", cached=True, read_at=read_at),
        ],
    )
    fresh = DynamoStore(store.client, store.table) if isinstance(store, DynamoStore) else store
    first, second = fresh.list_tool_calls(a.id)
    assert first.output_json == output and bool(first.cached) is False
    assert first.read_at.replace(tzinfo=UTC) == read_at
    assert second.output_json is None and second.cached is True


def test_sqlite_databases_from_before_get_the_new_columns(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from app.storage.db import add_missing_columns

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # the table as the first release created it
        conn.execute(
            text(
                "CREATE TABLE toolcallrecord (id VARCHAR PRIMARY KEY, message_id VARCHAR, "
                "seq INTEGER, tool VARCHAR, input_json VARCHAR, output_summary VARCHAR, "
                "status VARCHAR, error VARCHAR, duration_ms INTEGER)"
            )
        )
        conn.execute(text("INSERT INTO toolcallrecord (id, tool) VALUES ('tc_old', 'x')"))
    added = add_missing_columns(engine)
    assert {"toolcallrecord.output_json", "toolcallrecord.read_at", "toolcallrecord.cached"} <= set(
        added
    )
    columns = {c["name"] for c in inspect(engine).get_columns("toolcallrecord")}
    assert {"output_json", "read_at", "cached"} <= columns
    assert add_missing_columns(engine) == []  # idempotent


def test_deletes_cascade(store):
    conn = store.create_connection(_conn("x", T0))
    conv = store.create_conversation(Conversation(connection_id=conn.id))
    msg = store.add_message(
        Message(conversation_id=conv.id, role="assistant", content="a"),
        [ToolCallRecord(tool="get_caller_identity")],
    )
    other = store.create_conversation(Conversation(connection_id=conn.id))

    store.delete_conversation(other)
    assert store.get_conversation(other.id) is None
    assert store.get_conversation(conv.id) is not None

    store.delete_connection(conn)
    assert store.get_connection(conn.id) is None
    assert store.get_conversation(conv.id) is None
    assert store.list_messages(conv.id) == []
    fresh = DynamoStore(store.client, store.table) if isinstance(store, DynamoStore) else store
    assert fresh.list_tool_calls(msg.id) == []
    if isinstance(store, DynamoStore):
        assert store.client.scan(TableName=store.table)["Count"] == 0


def test_dynamodb_table_is_encrypted_and_indexed(aws):
    client = aws.client("dynamodb")
    assert ensure_table(client, "autoaws-enc") is True
    assert ensure_table(client, "autoaws-enc") is False  # idempotent
    table = client.describe_table(TableName="autoaws-enc")["Table"]
    assert {i["IndexName"] for i in table["GlobalSecondaryIndexes"]} == {"GSI1", "ById"}
    assert table["SSEDescription"]["Status"] in ("ENABLED", "ENABLING")


# ---- the whole API on DynamoDB ------------------------------------------------


@pytest.fixture
def dynamo_api(app, aws):
    client = aws.client("dynamodb")
    ensure_table(client, "autoaws-api")
    app.dependency_overrides[get_store] = lambda: DynamoStore(client, "autoaws-api")
    with TestClient(app) as c:
        yield c, client
    app.dependency_overrides.clear()


def test_api_flow_on_dynamodb(dynamo_api, aws):
    api, ddb = dynamo_api
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)

    conn = api.post(
        "/api/connections",
        json={
            "type": "access_key",
            "name": "ddb",
            "region": REGION,
            "access_key_id": FAKE_KEY,
            "secret_access_key": FAKE_SECRET,
        },
    ).json()["data"]
    assert api.post(f"/api/connections/{conn['id']}/verify").json()["data"]["status"] == "connected"
    assert api.get(f"/api/connections/{conn['id']}").json()["data"]["status"] == "connected"
    conv = api.post("/api/conversations", json={"connection_id": conn["id"]}).json()["data"]

    with api.stream(
        "POST",
        f"/api/conversations/{conv['id']}/messages",
        json={"content": "I can't SSH into my instance"},
    ) as r:
        events = [
            line.split(":", 1)[1].strip() for line in r.iter_lines() if line.startswith("event:")
        ]
    assert events[-2:] == ["answer", "done"]

    got = api.get(f"/api/conversations/{conv['id']}").json()["data"]
    assert got["title"] == "I can't SSH into my instance"
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][1]["answer"] is not None
    assert {t["tool"] for t in got["messages"][1]["tool_calls"]} >= {"describe_instances"}
    listed = api.get(f"/api/conversations?connection_id={conn['id']}").json()["data"]
    assert [c["id"] for c in listed] == [conv["id"]]

    assert api.delete(f"/api/connections/{conn['id']}").json()["data"] is None
    assert api.get(f"/api/conversations/{conv['id']}").json()["error"] == "CONVERSATION_NOT_FOUND"
    assert ddb.scan(TableName="autoaws-api")["Count"] == 0


def test_proposals_round_trip_and_compare_and_set(store):
    from app.storage.models import Proposal

    conv = store.create_conversation(Conversation(connection_id="conn_prop"))
    old = store.create_proposal(
        Proposal(conversation_id=conv.id, action="associate_route_table", created_at=T0)
    )
    new = store.create_proposal(
        Proposal(
            conversation_id=conv.id,
            action="authorize_sg_ingress",
            params_json='{"port": 8080}',
            created_at=T0 + timedelta(seconds=1),
        )
    )
    store.create_proposal(Proposal(conversation_id="conv_other", action="upsert_a_record"))

    mine = store.list_proposals(conversation_id=conv.id)
    assert [p.id for p in mine] == [new.id, old.id]  # newest first
    assert store.get_proposal(new.id).params_json == '{"port": 8080}'

    # compare-and-set: only the first of two concurrent approvals wins
    a, b = store.get_proposal(old.id), store.get_proposal(old.id)
    a.status = "APPROVED"
    assert store.update_proposal(a, expected_status="PENDING_APPROVAL") is True
    b.status = "REJECTED"
    assert store.update_proposal(b, expected_status="PENDING_APPROVAL") is False
    assert store.get_proposal(old.id).status == "APPROVED"
    assert [p.id for p in store.list_proposals(conversation_id=conv.id, status="APPROVED")] == [
        old.id
    ]

    store.delete_conversation(conv)
    assert (
        store.get_proposal(old.id) is None and store.list_proposals(conversation_id=conv.id) == []
    )
