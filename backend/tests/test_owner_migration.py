"""Offline migration preserves graph ownership and quarantines legacy records."""

import pytest
from sqlalchemy import MetaData, text
from sqlmodel import Session, SQLModel, create_engine

from app.storage import migrate_owner as migration
from app.storage.dynamo import DynamoStore, ensure_table
from app.storage.models import Connection, Conversation, Job, Message, Proposal, ToolCallRecord
from app.storage.sql import SqlStore


@pytest.fixture(params=["sqlite", "dynamodb"])
def migration_env(request, tmp_path, aws, monkeypatch):
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
        legacy_metadata = MetaData()
        for table in SQLModel.metadata.sorted_tables:
            copy = table.to_metadata(legacy_metadata)
            copy.c.user_id.nullable = True  # same as ALTER TABLE on a pre-auth database
        legacy_metadata.create_all(engine)
        monkeypatch.setattr(migration, "get_engine", lambda: engine)
        monkeypatch.setattr(migration, "init_db", lambda: None)
        with Session(engine) as session:
            yield SqlStore(session), lambda uid: SqlStore(session, uid), migration.migrate_sqlite
    else:
        from types import SimpleNamespace

        client = aws.client("dynamodb")
        table = "migration-test"
        ensure_table(client, table)
        monkeypatch.setattr(migration, "dynamodb_client", lambda: client)
        monkeypatch.setattr(
            migration, "get_settings", lambda: SimpleNamespace(dynamodb_table=table)
        )
        yield (
            DynamoStore(client, table),
            lambda uid: DynamoStore(client, table, uid),
            migration.migrate_dynamodb,
        )


def seed(store):
    conn = store.create_connection(Connection(name="demo", type="role", region="ap-southeast-1"))
    conv = store.create_conversation(Conversation(connection_id=conn.id))
    msg = store.add_message(
        Message(conversation_id=conv.id, role="assistant"), [ToolCallRecord(tool="test")]
    )
    job = store.create_job(Job(conversation_id=conv.id, status="succeeded"))
    prop = store.create_proposal(
        Proposal(conversation_id=conv.id, action="associate_route_table", status="REJECTED")
    )
    return conn, conv, msg, job, prop


def make_legacy(store):
    if isinstance(store, SqlStore):
        for table in SQLModel.metadata.sorted_tables:
            store.db.exec(text(f'UPDATE "{table.name}" SET user_id = NULL'))
        store.db.commit()
        store.db.expire_all()
    else:
        for raw in store.client.scan(TableName=store.table)["Items"]:
            old_key = {key: raw[key] for key in ("PK", "SK")}
            for key in ("PK", "GSI1PK"):
                if key in raw:
                    raw[key] = {"S": raw[key]["S"].removeprefix("USER#local-dev#")}
            raw.pop("user_id")
            for call in raw.get("tool_calls", {}).get("L", []):
                call["M"].pop("user_id", None)
            store.client.put_item(TableName=store.table, Item=raw)
            store.client.delete_item(TableName=store.table, Key=old_key)


@pytest.mark.parametrize("legacy", [False, True])
def test_migration_is_explicit_complete_and_rerunnable(migration_env, legacy):
    store, scoped, migrate = migration_env
    conn, conv, msg, job, prop = seed(store)
    if legacy:
        make_legacy(store)
    target = scoped("alice")
    assert target.get_connection(conn.id) is None
    count = migrate(None if legacy else "local-dev", "alice", False)
    assert count >= 5
    assert target.get_connection(conn.id) is None  # dry-run never assigns records
    assert migrate(None if legacy else "local-dev", "alice", True) == count
    if hasattr(store, "db"):
        store.db.expire_all()
    assert target.get_connection(conn.id).user_id == "alice"
    assert target.get_conversation(conv.id).user_id == "alice"
    assert target.get_job(job.id).user_id == "alice"
    assert target.get_proposal(prop.id).user_id == "alice"
    assert target.list_messages(conv.id)[0].user_id == "alice"
    assert target.list_tool_calls(msg.id)[0].user_id == "alice"
    assert scoped("bob").list_connections() == []
    assert migrate(None if legacy else "local-dev", "alice", True) == 0


def test_migration_refuses_active_background_work(migration_env):
    store, _, migrate = migration_env
    store.create_job(Job(conversation_id="c", status="running"))
    with pytest.raises(ValueError, match="active jobs"):
        migrate("local-dev", "alice", True)
