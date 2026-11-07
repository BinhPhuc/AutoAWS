import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.agent.loop import run_agent
from app.api.schemas import ConversationIn, ConversationOut, MessageIn, MessageOut
from app.aws.credentials import CredentialError, resolve_session
from app.errors import AppError, NotFound
from app.llm.base import LLMError
from app.llm.factory import get_provider
from app.responses import ok
from app.storage.base import Store
from app.storage.models import Conversation
from app.storage.store import get_store

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _get(store: Store, conv_id: str) -> Conversation:
    conv = store.get_conversation(conv_id)
    if conv is None:
        raise NotFound("CONVERSATION_NOT_FOUND", "Conversation not found")
    return conv


def _connected(store: Store, connection_id: str):
    conn = store.get_connection(connection_id)
    if conn is None:
        raise NotFound("CONNECTION_NOT_FOUND", "Connection not found")
    if conn.status != "connected":
        raise AppError("CONNECTION_NOT_VERIFIED", 400, "Connection is not verified yet")
    return conn


@router.post("")
def create_conversation(body: ConversationIn, store: Store = Depends(get_store)):
    _connected(store, body.connection_id)
    conv = store.create_conversation(Conversation(connection_id=body.connection_id))
    return ok(ConversationOut.from_model(conv), "Conversation created", 201)


@router.get("")
def list_conversations(connection_id: str | None = None, store: Store = Depends(get_store)):
    return ok([ConversationOut.from_model(c) for c in store.list_conversations(connection_id)])


@router.get("/{conv_id}")
def get_conversation(conv_id: str, store: Store = Depends(get_store)):
    conv = _get(store, conv_id)
    messages = [
        MessageOut.from_model(m, store.list_tool_calls(m.id)) for m in store.list_messages(conv.id)
    ]
    return ok(ConversationOut.from_model(conv, messages))


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str, store: Store = Depends(get_store)):
    store.delete_conversation(_get(store, conv_id))
    return ok(None, "Conversation deleted")


@router.post("/{conv_id}/messages")
async def send_message(conv_id: str, body: MessageIn, store: Store = Depends(get_store)):
    conv = _get(store, conv_id)
    conn = _connected(store, conv.connection_id)
    try:
        aws_session = resolve_session(conn)
    except CredentialError as e:
        raise AppError("AWS_AUTH_FAILED", 400, f"AWS authentication failed: {e}") from e
    try:
        provider = get_provider()
    except LLMError as e:
        raise AppError("LLM_UNAVAILABLE", 503, f"LLM provider is unavailable: {e}") from e

    async def events():
        async for event in run_agent(store, conv, body.content, aws_session, provider):
            yield {"event": event.type, "data": json.dumps(event.data, default=str)}

    return EventSourceResponse(events(), ping=15)
