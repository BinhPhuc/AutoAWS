"""DynamoDB implementation of the Store (single-table design).

Items (PK / SK):
  connection    CONN#<id>              / META                      GSI1: CONNECTIONS
  conversation  CONV#<id>              / META                      GSI1: CONVS#<connection_id>
  message       CONV#<conversation_id> / MSG#<created_at>#<id>     (tool calls embedded)

Indexes:
  GSI1  (GSI1PK, GSI1SK)  listings — connections newest first, conversations of a connection
                          most recently updated first (GSI1SK = <timestamp>#<id>)
  ById  (id)              any item by its id; used to load one message's tool calls

Attributes are the model fields as JSON types (datetimes as ISO-8601 UTC). Sort keys use a
fixed-width timestamp so string order equals time order. Tool calls are always written and
read with their message, so they live inside the message item. The table is encrypted with
KMS (AWS managed key unless DYNAMODB_KMS_KEY_ID is set).

Uses the low-level client (thread-safe; FastAPI runs sync routes in a thread pool).
GSIs are eventually consistent: a listing right after a write may lag by a few ms.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from app.storage.models import Connection, Conversation, Message, ToolCallRecord, utcnow

log = logging.getLogger(__name__)

GSI1 = "GSI1"
BY_ID = "ById"
_KEY_ATTRS = {"PK", "SK", "GSI1PK", "GSI1SK", "entity"}
_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _ts(dt: datetime) -> str:
    """Fixed-width UTC timestamp for sort keys (Pydantic drops zero microseconds)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ensure_table(client, table: str, kms_key_id: str = "") -> bool:
    """Create the table and its indexes if missing (dev / LocalStack). True if created."""
    try:
        client.describe_table(TableName=table)
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    sse = {"Enabled": True, "SSEType": "KMS"}
    if kms_key_id:
        sse["KMSMasterKeyId"] = kms_key_id
    client.create_table(
        TableName=table,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": name, "AttributeType": "S"}
            for name in ("PK", "SK", "GSI1PK", "GSI1SK", "id")
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": GSI1,
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": BY_ID,
                "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        SSESpecification=sse,
    )
    client.get_waiter("table_exists").wait(TableName=table)
    log.info("Created DynamoDB table %s", table)
    return True


class DynamoStore:
    def __init__(self, client, table: str) -> None:
        self.client = client
        self.table = table
        # Tool calls of the messages this store has seen. A store lives for one request,
        # so the cache never goes stale (tool calls are immutable once written).
        self._tool_calls: dict[str, list[ToolCallRecord]] = {}

    # ---- connections ---------------------------------------------------------

    def create_connection(self, conn: Connection) -> Connection:
        self._put(self._connection_item(conn), new=True)
        return conn

    def list_connections(self) -> list[Connection]:
        return [Connection.model_validate(self._fields(i)) for i in self._query_gsi1("CONNECTIONS")]

    def get_connection(self, conn_id: str) -> Connection | None:
        item = self._get(f"CONN#{conn_id}", "META")
        return Connection.model_validate(self._fields(item)) if item else None

    def save_connection(self, conn: Connection) -> None:
        self._put(self._connection_item(conn))

    def delete_connection(self, conn: Connection) -> None:
        for conv in self.list_conversations(conn.id):
            self.delete_conversation(conv)
        self._delete_keys([(f"CONN#{conn.id}", "META")])

    # ---- conversations -------------------------------------------------------

    def create_conversation(self, conv: Conversation) -> Conversation:
        self._put(self._conversation_item(conv), new=True)
        return conv

    def list_conversations(self, connection_id: str | None = None) -> list[Conversation]:
        conn_ids = [connection_id] if connection_id else [c.id for c in self.list_connections()]
        convs = [
            Conversation.model_validate(self._fields(item))
            for cid in conn_ids
            for item in self._query_gsi1(f"CONVS#{cid}")
        ]
        return sorted(convs, key=lambda c: c.updated_at, reverse=True)

    def get_conversation(self, conv_id: str) -> Conversation | None:
        item = self._get(f"CONV#{conv_id}", "META")
        return Conversation.model_validate(self._fields(item)) if item else None

    def delete_conversation(self, conv: Conversation) -> None:
        # The conversation item and all its messages share the partition CONV#<id>.
        self._delete_keys([(i["PK"]["S"], i["SK"]["S"]) for i in self._query(f"CONV#{conv.id}")])

    def touch_conversation(self, conv: Conversation, title: str | None = None) -> None:
        conv.updated_at = utcnow()
        if title and not conv.title:
            conv.title = title
        self._put(self._conversation_item(conv))

    # ---- messages ------------------------------------------------------------

    def add_message(self, msg: Message, tool_calls: list[ToolCallRecord] | None = None) -> Message:
        calls = list(tool_calls or [])
        for i, tc in enumerate(calls):
            tc.message_id = msg.id
            tc.seq = i
        item = self._message_item(msg)
        item["tool_calls"] = [tc.model_dump(mode="json", exclude={"message_id"}) for tc in calls]
        self._put(item, new=True)
        self._tool_calls[msg.id] = calls
        return msg

    def list_messages(self, conv_id: str) -> list[Message]:
        messages = []
        for raw in self._query(f"CONV#{conv_id}", sk_prefix="MSG#"):
            fields = self._fields(raw)
            calls = fields.pop("tool_calls", None) or []
            msg = Message.model_validate(fields)
            self._tool_calls[msg.id] = self._tool_call_models(msg.id, calls)
            messages.append(msg)
        return messages

    def list_tool_calls(self, message_id: str) -> list[ToolCallRecord]:
        if message_id not in self._tool_calls:
            item = next(
                (
                    self._fields(i)
                    for i in self._query_index(BY_ID, "id", message_id)
                    if i.get("entity", {}).get("S") == "message"
                ),
                {},
            )
            self._tool_calls[message_id] = self._tool_call_models(
                message_id, item.get("tool_calls") or []
            )
        return list(self._tool_calls[message_id])

    # ---- items -----------------------------------------------------------------

    @staticmethod
    def _connection_item(conn: Connection) -> dict:
        return {
            "PK": f"CONN#{conn.id}",
            "SK": "META",
            "GSI1PK": "CONNECTIONS",
            "GSI1SK": f"{_ts(conn.created_at)}#{conn.id}",
            "entity": "connection",
            **conn.model_dump(mode="json"),
        }

    @staticmethod
    def _conversation_item(conv: Conversation) -> dict:
        return {
            "PK": f"CONV#{conv.id}",
            "SK": "META",
            "GSI1PK": f"CONVS#{conv.connection_id}",
            "GSI1SK": f"{_ts(conv.updated_at)}#{conv.id}",
            "entity": "conversation",
            **conv.model_dump(mode="json"),
        }

    @staticmethod
    def _message_item(msg: Message) -> dict:
        return {
            "PK": f"CONV#{msg.conversation_id}",
            "SK": f"MSG#{_ts(msg.created_at)}#{msg.id}",
            "entity": "message",
            **msg.model_dump(mode="json"),
        }

    @staticmethod
    def _tool_call_models(message_id: str, calls: list[dict]) -> list[ToolCallRecord]:
        models = [ToolCallRecord.model_validate({**c, "message_id": message_id}) for c in calls]
        return sorted(models, key=lambda t: t.seq)

    @staticmethod
    def _fields(item: dict) -> dict:
        return {k: _deserializer.deserialize(v) for k, v in item.items() if k not in _KEY_ATTRS}

    # ---- low-level calls -------------------------------------------------------

    def _put(self, attrs: dict, new: bool = False) -> None:
        kwargs = {"ConditionExpression": "attribute_not_exists(PK)"} if new else {}
        self.client.put_item(
            TableName=self.table,
            Item={k: _serializer.serialize(v) for k, v in attrs.items()},
            **kwargs,
        )

    def _get(self, pk: str, sk: str) -> dict | None:
        resp = self.client.get_item(
            TableName=self.table, Key={"PK": {"S": pk}, "SK": {"S": sk}}, ConsistentRead=True
        )
        return resp.get("Item")

    def _query(self, pk: str, sk_prefix: str | None = None) -> Iterator[dict]:
        condition = "PK = :pk"
        values = {":pk": {"S": pk}}
        if sk_prefix:
            condition += " AND begins_with(SK, :sk)"
            values[":sk"] = {"S": sk_prefix}
        yield from self._paginate(
            KeyConditionExpression=condition,
            ExpressionAttributeValues=values,
            ConsistentRead=True,
        )

    def _query_gsi1(self, pk: str) -> Iterator[dict]:
        yield from self._paginate(
            IndexName=GSI1,
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": {"S": pk}},
            ScanIndexForward=False,
        )

    def _query_index(self, index: str, attr: str, value: str) -> Iterator[dict]:
        yield from self._paginate(
            IndexName=index,
            KeyConditionExpression="#a = :v",
            ExpressionAttributeNames={"#a": attr},
            ExpressionAttributeValues={":v": {"S": value}},
        )

    def _paginate(self, **kwargs) -> Iterator[dict]:
        for page in self.client.get_paginator("query").paginate(TableName=self.table, **kwargs):
            yield from page.get("Items", [])

    def _delete_keys(self, keys: list[tuple[str, str]]) -> None:
        for start in range(0, len(keys), 25):  # BatchWriteItem limit
            requests = [
                {"DeleteRequest": {"Key": {"PK": {"S": pk}, "SK": {"S": sk}}}}
                for pk, sk in keys[start : start + 25]
            ]
            pending = {self.table: requests}
            for _ in range(5):
                resp = self.client.batch_write_item(RequestItems=pending)
                pending = resp.get("UnprocessedItems") or {}
                if not pending:
                    break
            else:
                raise RuntimeError(f"DynamoDB did not process {len(pending[self.table])} deletes")
