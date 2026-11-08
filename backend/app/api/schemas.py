"""Request/response shapes exposed over HTTP. Mirrors docs/API_CONTRACT.md."""

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.agent.schemas import DiagnosisAnswer
from app.storage.models import Connection, Conversation, Message, ToolCallRecord

# ---- connections -------------------------------------------------------------


class AccessKeyConnectionIn(BaseModel):
    type: Literal["access_key"]
    name: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1)
    access_key_id: str = Field(pattern=r"^[A-Z0-9]{16,32}$")
    secret_access_key: str = Field(min_length=16)


class RoleConnectionIn(BaseModel):
    type: Literal["role"]
    name: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1)
    role_arn: str = Field(pattern=r"^arn:aws:iam::\d{12}:role/.+")
    external_id: str | None = None


ConnectionIn = Annotated[AccessKeyConnectionIn | RoleConnectionIn, Field(discriminator="type")]


class ConnectionOut(BaseModel):
    id: str
    name: str
    type: str
    region: str
    status: str
    account_id: str | None
    role_arn: str | None
    external_id: str | None
    access_key_id_masked: str | None
    last_verified_at: datetime | None
    last_error: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, c: Connection) -> "ConnectionOut":
        masked = None
        if c.access_key_id:
            masked = c.access_key_id[:4] + "****" + c.access_key_id[-4:]
        return cls(
            id=c.id,
            name=c.name,
            type=c.type,
            region=c.region,
            status=c.status,
            account_id=c.account_id,
            role_arn=c.role_arn,
            external_id=c.external_id,
            access_key_id_masked=masked,
            last_verified_at=c.last_verified_at,
            last_error=c.last_error,
            created_at=c.created_at,
        )


class VerifyOut(BaseModel):
    status: Literal["connected", "failed"]
    account_id: str | None
    arn: str | None
    checked_at: datetime
    error: str | None


class CloudFormationOut(BaseModel):
    stack_name: str
    role_name: str
    external_id: str
    platform_account_id: str
    template_yaml: str


# ---- conversations -----------------------------------------------------------


class ConversationIn(BaseModel):
    connection_id: str


class ToolCallOut(BaseModel):
    id: str
    tool: str
    input: dict
    output_summary: str
    status: str
    error: str | None
    duration_ms: int
    cached: bool = False

    @classmethod
    def from_model(cls, t: ToolCallRecord) -> "ToolCallOut":
        return cls(
            id=t.id,
            tool=t.tool,
            input=json.loads(t.input_json or "{}"),
            output_summary=t.output_summary,
            status=t.status,
            error=t.error,
            duration_ms=t.duration_ms,
            cached=bool(t.cached),
        )


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    answer: DiagnosisAnswer | None
    tool_calls: list[ToolCallOut]
    created_at: datetime

    @classmethod
    def from_model(cls, m: Message, tool_calls: list[ToolCallRecord]) -> "MessageOut":
        answer = DiagnosisAnswer.model_validate_json(m.answer_json) if m.answer_json else None
        return cls(
            id=m.id,
            role=m.role,
            content=m.content,
            answer=answer,
            tool_calls=[ToolCallOut.from_model(t) for t in tool_calls],
            created_at=m.created_at,
        )


class ConversationOut(BaseModel):
    id: str
    connection_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] | None = None

    @classmethod
    def from_model(
        cls, c: Conversation, messages: list[MessageOut] | None = None
    ) -> "ConversationOut":
        return cls(
            id=c.id,
            connection_id=c.connection_id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            messages=messages,
        )


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


# ---- tools -------------------------------------------------------------------


class ToolOut(BaseModel):
    name: str
    group: str
    label: str
    description: str
    input_schema: dict
    aws_actions: list[str]
