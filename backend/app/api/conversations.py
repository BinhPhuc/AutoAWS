import json

from fastapi import APIRouter, Depends
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse

from app.agent.loop import run_agent
from app.api.schemas import ConversationIn, ConversationOut, MessageIn, MessageOut
from app.aws.credentials import CredentialError, resolve_session
from app.errors import AppError, NotFound
from app.llm.base import LLMError
from app.llm.factory import get_provider
from app.responses import ok
from app.storage import repo
from app.storage.db import get_session
from app.storage.models import Conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _get(db: Session, conv_id: str) -> Conversation:
    conv = repo.get_conversation(db, conv_id)
    if conv is None:
        raise NotFound("CONVERSATION_NOT_FOUND", "Conversation not found")
    return conv


def _connected(db: Session, connection_id: str):
    conn = repo.get_connection(db, connection_id)
    if conn is None:
        raise NotFound("CONNECTION_NOT_FOUND", "Connection not found")
    if conn.status != "connected":
        raise AppError("CONNECTION_NOT_VERIFIED", 400, "Connection is not verified yet")
    return conn


@router.post("")
def create_conversation(body: ConversationIn, db: Session = Depends(get_session)):
    _connected(db, body.connection_id)
    conv = repo.create_conversation(db, Conversation(connection_id=body.connection_id))
    return ok(ConversationOut.from_model(conv), "Conversation created", 201)


@router.get("")
def list_conversations(connection_id: str | None = None, db: Session = Depends(get_session)):
    return ok([ConversationOut.from_model(c) for c in repo.list_conversations(db, connection_id)])


@router.get("/{conv_id}")
def get_conversation(conv_id: str, db: Session = Depends(get_session)):
    conv = _get(db, conv_id)
    messages = [
        MessageOut.from_model(m, repo.list_tool_calls(db, m.id))
        for m in repo.list_messages(db, conv.id)
    ]
    return ok(ConversationOut.from_model(conv, messages))


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str, db: Session = Depends(get_session)):
    repo.delete_conversation(db, _get(db, conv_id))
    return ok(None, "Conversation deleted")


@router.post("/{conv_id}/messages")
async def send_message(conv_id: str, body: MessageIn, db: Session = Depends(get_session)):
    conv = _get(db, conv_id)
    conn = _connected(db, conv.connection_id)
    try:
        aws_session = resolve_session(conn)
    except CredentialError as e:
        raise AppError("AWS_AUTH_FAILED", 400, f"AWS authentication failed: {e}") from e
    try:
        provider = get_provider()
    except LLMError as e:
        raise AppError("LLM_UNAVAILABLE", 503, f"LLM provider is unavailable: {e}") from e

    async def events():
        async for event in run_agent(db, conv, body.content, aws_session, provider):
            yield {"event": event.type, "data": json.dumps(event.data, default=str)}

    return EventSourceResponse(events(), ping=15)
