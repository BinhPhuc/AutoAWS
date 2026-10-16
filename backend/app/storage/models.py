"""SQLModel tables. Kept deliberately flat so they map 1:1 to DynamoDB items later."""

import secrets
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Connection(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("conn"), primary_key=True)
    name: str
    type: str  # "access_key" | "role"
    region: str
    status: str = "pending"  # pending | connected | failed
    account_id: str | None = None
    role_arn: str | None = None
    external_id: str | None = None
    # Dev-only storage of long-term keys (see BACKEND_PLAN §4.1). Never serialized to clients.
    access_key_id: str | None = None
    secret_access_key: str | None = None
    last_verified_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("conv"), primary_key=True)
    connection_id: str = Field(index=True)
    title: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("msg"), primary_key=True)
    conversation_id: str = Field(index=True)
    role: str  # user | assistant
    content: str = ""
    answer_json: str | None = None  # DiagnosisAnswer as JSON (assistant only)
    created_at: datetime = Field(default_factory=utcnow)


class ToolCallRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("tc"), primary_key=True)
    message_id: str = Field(index=True)
    seq: int = 0
    tool: str
    input_json: str = "{}"
    output_summary: str = ""
    status: str = "ok"  # ok | error
    error: str | None = None
    duration_ms: int = 0
