from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.schemas import ConversationIn, ConversationOut, JobOut, MessageIn, MessageOut
from app.errors import AppError, NotFound
from app.platform import dispatch
from app.responses import ok
from app.storage.base import Store
from app.storage.models import Conversation
from app.storage.store import get_store
from app.worker import ACTIVE, expire_stale, new_job

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
def send_message(
    conv_id: str,
    body: MessageIn,
    background: BackgroundTasks,
    store: Store = Depends(get_store),
):
    """Start a diagnosis job (docs/API_CONTRACT.md §3, §8); the client polls the job."""
    conv = _get(store, conv_id)
    _connected(store, conv.connection_id)
    for job in store.list_jobs(conv.id):
        if expire_stale(store, job).status in ACTIVE:
            raise AppError(
                "JOB_IN_PROGRESS", 409, "A diagnosis is already running in this conversation"
            )
    job = store.create_job(new_job(conv, body.content))
    try:
        dispatch.start_job(job.id, background)
    except dispatch.DispatchError as e:
        store.update_job(job.id, status="failed", error_json='{"error": "INTERNAL"}')
        raise AppError("INTERNAL", 500, "Could not start the diagnosis") from e
    return ok(JobOut.from_model(job), "Diagnosis started", 202)
