"""SQLModel tables. Kept deliberately flat so they map 1:1 to DynamoDB items later."""

import secrets
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

# Owner of data created without sign-in (AUTH_MODE=none) and of rows from before user_id
LOCAL_USER_ID = "local"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Connection(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("conn"), primary_key=True)
    user_id: str = Field(default=LOCAL_USER_ID, index=True)  # owner (docs/API_CONTRACT.md §0.1)
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
    # Optional AutoAWSRemediation role (CloudFormation EnableRemediation=true): executes
    # approved proposals. Never used for reads.
    remediation_role_arn: str | None = None
    last_verified_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("conv"), primary_key=True)
    user_id: str = Field(default=LOCAL_USER_ID, index=True)
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
    # Sanitized result (capped, see agent/loop.py): conversation cache + evidence checks.
    # Never sent to clients. None: too large to keep, a cache hit, or an older record.
    output_json: str | None = None
    read_at: datetime | None = None
    cached: bool | None = False  # served from the conversation cache, no AWS call


class Proposal(SQLModel, table=True):
    """A remediation the agent proposed; executed only after the user approves it."""

    id: str = Field(default_factory=lambda: new_id("prop"), primary_key=True)
    user_id: str = Field(default=LOCAL_USER_ID, index=True)  # owner of the conversation
    conversation_id: str = Field(index=True)
    message_id: str = ""
    connection_id: str = ""
    kind: str = "fix"  # fix | rollback
    parent_id: str | None = None
    action: str
    params_json: str = "{}"
    reason: str = ""
    status: str = "PENDING_APPROVAL"
    preview_json: str = "{}"
    # Resource state when the proposal was made (STALE check, rollback target)
    snapshot_json: str = "{}"
    snapshot_hash: str = ""
    result_json: str | None = None
    verification_json: str | None = None
    error: str | None = None
    history_json: str = "[]"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    # RUNTIME=lambda: Step Functions task token of the approval wait (never sent to clients)
    task_token: str | None = None


class Job(SQLModel, table=True):
    """One background diagnosis turn (docs/API_CONTRACT.md §8)."""

    id: str = Field(default_factory=lambda: new_id("job"), primary_key=True)
    user_id: str = Field(default=LOCAL_USER_ID, index=True)  # owner of the conversation
    type: str = "diagnosis"
    conversation_id: str = Field(index=True)
    question: str = ""
    status: str = "queued"  # queued | running | succeeded | failed | cancelled
    cancel_requested: bool = False
    message_id: str | None = None
    error_json: str | None = None
    events_json: str = "[]"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None  # DynamoDB TTL
