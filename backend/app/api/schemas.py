"""Request/response shapes exposed over HTTP. Mirrors docs/API_CONTRACT.md."""

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.agent.schemas import DiagnosisAnswer
from app.aws.remediation.sessions import remediation_enabled
from app.storage.models import (
    Connection,
    Conversation,
    Job,
    Message,
    Proposal,
    ToolCallRecord,
)

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
    external_id: str | None = Field(
        default=None, min_length=2, max_length=1224, pattern=r"^[A-Za-z0-9_+=,.@:/-]+$"
    )
    remediation_role_arn: str | None = Field(default=None, pattern=r"^arn:aws:iam::\d{12}:role/.+")


class ConnectionPatch(BaseModel):
    remediation_role_arn: str | None = Field(pattern=r"^arn:aws:iam::\d{12}:role/.+")


ConnectionIn = Annotated[AccessKeyConnectionIn | RoleConnectionIn, Field(discriminator="type")]


class CloudFormationPreviewIn(BaseModel):
    external_id: str = Field(min_length=2, max_length=1224, pattern=r"^[A-Za-z0-9_+=,.@:/-]+$")


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
    remediation_role_arn: str | None
    remediation_enabled: bool
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
            remediation_role_arn=c.remediation_role_arn,
            remediation_enabled=remediation_enabled(c),
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


# ---- remediation ---------------------------------------------------------------


class ProposalOut(BaseModel):
    id: str
    conversation_id: str
    message_id: str
    connection_id: str
    kind: str
    parent_id: str | None
    action: str
    params: dict
    reason: str
    status: str
    preview: dict
    result: dict | None
    verification: dict | None
    error: str | None
    history: list[dict]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None

    @classmethod
    def from_model(cls, p: Proposal) -> "ProposalOut":
        def load(text: str | None):
            return json.loads(text) if text else None

        return cls(
            id=p.id,
            conversation_id=p.conversation_id,
            message_id=p.message_id,
            connection_id=p.connection_id,
            kind=p.kind,
            parent_id=p.parent_id,
            action=p.action,
            params=load(p.params_json) or {},
            reason=p.reason,
            status=p.status,
            preview=load(p.preview_json) or {},
            result=load(p.result_json),
            verification=load(p.verification_json),
            error=p.error,
            history=load(p.history_json) or [],
            created_at=p.created_at,
            updated_at=p.updated_at,
            expires_at=p.expires_at,
        )


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "feedback"]
    feedback: str = Field(default="", max_length=2000)


class DecisionOut(BaseModel):
    proposal: ProposalOut
    followup_question: str | None


class RemediationActionOut(BaseModel):
    name: str
    label: str
    description: str
    input_schema: dict
    aws_actions: list[str]


# ---- jobs ------------------------------------------------------------------------


class JobOut(BaseModel):
    id: str
    type: str
    conversation_id: str
    status: str
    cancel_requested: bool
    message_id: str | None
    error: dict | None
    events: list[dict]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, j: Job, after: int = -1) -> "JobOut":
        events = json.loads(j.events_json or "[]")
        return cls(
            id=j.id,
            type=j.type,
            conversation_id=j.conversation_id,
            status=j.status,
            cancel_requested=bool(j.cancel_requested),
            message_id=j.message_id,
            error=json.loads(j.error_json) if j.error_json else None,
            events=[e for e in events if e["seq"] > after],
            created_at=j.created_at,
            updated_at=j.updated_at,
        )


class AuthConfigOut(BaseModel):
    mode: Literal["none", "cognito"]
    domain: str | None = None
    client_id: str | None = None
    scopes: list[str] = []


class MeOut(BaseModel):
    user_id: str
    username: str
    auth_mode: Literal["none", "cognito"]
