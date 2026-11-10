"""Offline, explicit ownership migration. Never invoked by the web application.

python -m app.storage.migrate_owner --from-user legacy --to-user <Cognito-sub> [--apply]
"""

import argparse
import re

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from sqlalchemy import func, select, update
from sqlmodel import SQLModel

from app.config import get_settings
from app.storage import models  # noqa: F401 — register tables
from app.storage.db import get_engine, init_db
from app.storage.store import dynamodb_client

ENTITIES = {"connection", "conversation", "message", "proposal", "job"}
ACTIVE_PROPOSALS = {"APPROVED", "RECHECKING", "EXECUTING", "VERIFYING"}


def _check_inactive(entity: str, fields: dict) -> None:
    if (entity == "job" and fields.get("status") in ("queued", "running")) or (
        entity == "proposal"
        and (fields.get("task_token") or fields.get("status") in ACTIVE_PROPOSALS)
    ):
        raise ValueError("Finish or cancel active jobs/workflows before migrating")


def migrate_sqlite(source: str | None, target: str, apply: bool) -> int:
    init_db()
    count = 0
    with get_engine().begin() as db:
        for table in SQLModel.metadata.sorted_tables:
            owner = table.c.user_id
            condition = owner.is_(None) if source is None else owner == source
            for row in db.execute(select(table).where(condition)).mappings():
                _check_inactive(table.name, dict(row))
            count += db.scalar(select(func.count()).select_from(table).where(condition))
        if apply:
            for table in SQLModel.metadata.sorted_tables:
                condition = (
                    table.c.user_id.is_(None) if source is None else table.c.user_id == source
                )
                db.execute(update(table).where(condition).values(user_id=target))
    return count


def migrate_dynamodb(source: str | None, target: str, apply: bool) -> int:
    settings = get_settings()
    client, table = dynamodb_client(), settings.dynamodb_table
    ser, de = TypeSerializer(), TypeDeserializer()
    moves = []
    for page in client.get_paginator("scan").paginate(TableName=table, ConsistentRead=True):
        for raw in page.get("Items", []):
            fields = {k: de.deserialize(v) for k, v in raw.items()}
            if fields.get("user_id") != source or fields.get("entity") not in ENTITIES:
                continue
            _check_inactive(fields["entity"], fields)
            item = dict(fields)
            item["user_id"] = target
            for attr in ("PK", "GSI1PK"):
                if attr not in item:
                    continue
                key = item[attr]
                if source is not None:
                    prefix = f"USER#{source}#"
                    if not key.startswith(prefix):
                        raise ValueError("Unexpected source partition; migration stopped")
                    key = key[len(prefix) :]
                elif key.startswith("USER#"):
                    raise ValueError("Unowned item already has a user partition")
                item[attr] = f"USER#{target}#{key}"
            for call in item.get("tool_calls") or []:
                call["user_id"] = target
            new_key = {k: ser.serialize(item[k]) for k in ("PK", "SK")}
            if client.get_item(TableName=table, Key=new_key, ConsistentRead=True).get("Item"):
                raise ValueError("Destination item already exists; migration stopped")
            moves.append((raw, {k: ser.serialize(v) for k, v in item.items()}))
    # Preflight all collisions before the first mutation. Each move is atomic and rerunnable.
    if apply:
        for old, new in moves:
            condition = "attribute_not_exists(user_id)" if source is None else "user_id = :owner"
            extra = (
                {} if source is None else {"ExpressionAttributeValues": {":owner": {"S": source}}}
            )
            client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": table,
                            "Item": new,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {
                        "Delete": {
                            "TableName": table,
                            "Key": {k: old[k] for k in ("PK", "SK")},
                            "ConditionExpression": condition,
                            **extra,
                        }
                    },
                ]
            )
    return len(moves)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-user", required=True, help="legacy (no owner), local-dev, or Cognito sub"
    )
    parser.add_argument("--to-user", required=True, help="Explicit destination Cognito sub")
    parser.add_argument(
        "--apply", action="store_true", help="Apply; default only counts and validates"
    )
    args = parser.parse_args()
    source = None if args.from_user == "legacy" else args.from_user
    for value in (source, args.to_user):
        if value is not None and not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value):
            parser.error("Invalid user ID")
    if source == args.to_user or args.to_user == "legacy":
        parser.error("Source and destination must differ; legacy is not a destination")
    migrate = migrate_dynamodb if get_settings().storage_backend == "dynamodb" else migrate_sqlite
    count = migrate(source, args.to_user, args.apply)
    print(f"{'Migrated' if args.apply else 'Would migrate'} {count} records")


if __name__ == "__main__":
    main()
