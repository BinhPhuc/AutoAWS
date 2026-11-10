"""Background work of AutoAWS — what the agent-worker Lambda runs (docs/API_CONTRACT.md §8–§9).

- ``run_job``: one diagnosis turn; every agent event is appended to the Job, which the client
  polls. Cancellation is a flag on the job, checked between events.
- ``verify_connection``: AssumeRole + one read, so the api-handler never needs access to a
  user's account.
- ``expire_stale``: a job whose worker died (timeout, crash) ends as failed.

RUNTIME=local runs these in the FastAPI process (BackgroundTasks); the code is the same.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from app.agent.loop import STOPPED_NOTE, run_agent
from app.api.schemas import VerifyOut
from app.aws.credentials import CredentialError, forget_session, resolve_session, verify_session
from app.config import get_settings
from app.llm.base import LLMError
from app.llm.factory import get_provider
from app.storage.base import Store
from app.storage.models import Conversation, Job, Message, utcnow
from app.storage.store import open_store

log = logging.getLogger(__name__)

ACTIVE = ("queued", "running")


def new_job(conversation: Conversation, question: str) -> Job:
    return Job(
        user_id=conversation.user_id,
        conversation_id=conversation.id,
        question=question,
        expires_at=utcnow() + timedelta(days=get_settings().job_ttl_days),
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def expire_stale(store: Store, job: Job) -> Job:
    """A queued/running job without updates for JOB_STALE_SECONDS lost its worker."""
    if job.status not in ACTIVE:
        return job
    age = (datetime.now(UTC) - _aware(job.updated_at)).total_seconds()
    if age < get_settings().job_stale_seconds:
        return job
    error = {"error": "WORKER_LOST", "message": "The diagnosis worker stopped unexpectedly"}
    events = json.loads(job.events_json or "[]")
    events += [
        {"seq": len(events), "type": "error", "data": error},
        {"seq": len(events) + 1, "type": "done", "data": {}},
    ]
    store.update_job(
        job.id, status="failed", error_json=json.dumps(error), events_json=json.dumps(events)
    )
    # The turn started (question stored) but never answered: keep user/assistant alternating.
    messages = store.list_messages(job.conversation_id)
    if messages and messages[-1].role == "user":
        conv = store.get_conversation(job.conversation_id)
        store.add_message(
            Message(
                conversation_id=job.conversation_id,
                role="assistant",
                content="Chưa hoàn thành chẩn đoán: tiến trình chẩn đoán bị dừng đột ngột.",
            )
        )
        if conv:
            store.touch_conversation(conv)
    return store.get_job(job.id) or job


class _JobLog:
    """Appends events to the job as they happen."""

    def __init__(self, store: Store, job_id: str) -> None:
        self.store = store
        self.job_id = job_id
        self.events: list[dict] = []

    def emit(self, type_: str, data: dict) -> None:
        self.events.append({"seq": len(self.events), "type": type_, "data": data})
        self.store.update_job(self.job_id, events_json=json.dumps(self.events, default=str))

    def fail_before_start(self, conv: Conversation, question: str, code: str, message: str):
        """The agent could not even start: store the turn so history stays consistent."""
        self.store.add_message(Message(conversation_id=conv.id, role="user", content=question))
        self.store.add_message(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content=f"Chưa hoàn thành chẩn đoán: {message}",
            )
        )
        self.store.touch_conversation(conv, title=question[:80])
        error = {"error": code, "message": message}
        self.emit("error", error)
        self.emit("done", {})
        self.store.update_job(self.job_id, status="failed", error_json=json.dumps(error))


async def run_job(job_id: str) -> None:
    """Run one queued diagnosis job to the end. Never raises."""
    with open_store() as store:
        job = store.get_job(job_id)
        if job is None or job.status != "queued":
            return  # unknown, or already picked up (a duplicate invocation)
        store.update_job(job_id, status="running")
        out = _JobLog(store, job_id)
        conv = store.get_conversation(job.conversation_id)
        conn = store.get_connection(conv.connection_id) if conv else None
        if conv is None or conn is None:
            out.emit("error", {"error": "CONVERSATION_NOT_FOUND", "message": "Not found"})
            out.emit("done", {})
            store.update_job(job_id, status="failed")
            return
        try:
            session = resolve_session(conn)
        except CredentialError as e:
            out.fail_before_start(
                conv, job.question, "AWS_AUTH_FAILED", f"AWS authentication failed: {e}"
            )
            return
        try:
            provider = get_provider()
        except LLMError as e:
            out.fail_before_start(
                conv, job.question, "LLM_UNAVAILABLE", f"LLM provider is unavailable: {e}"
            )
            return

        status, message_id, error = "failed", None, None
        agent = run_agent(store, conv, job.question, session, provider)
        try:
            async for event in agent:
                out.emit(event.type, event.data)
                if event.type == "answer":
                    status, message_id = "succeeded", event.data["message_id"]
                elif event.type == "error":
                    error = event.data
                fresh = store.get_job(job_id)
                if fresh is not None and fresh.cancel_requested and event.type != "done":
                    await agent.aclose()  # stores STOPPED_NOTE as the assistant message
                    status = "cancelled"
                    out.emit("error", {"error": "CANCELLED", "message": "Stopped by the user"})
                    out.emit("done", {})
                    break
        except Exception as e:  # noqa: BLE001 — a job must end in a final state
            log.exception("Job %s crashed", job_id)
            error = {"error": "INTERNAL", "message": f"{type(e).__name__}"}
            out.emit("error", error)
            out.emit("done", {})
        store.update_job(
            job_id,
            status=status,
            message_id=message_id,
            error_json=json.dumps(error) if error else None,
        )


def verify_connection(store: Store, conn_id: str) -> dict:
    """AssumeRole / access key + one trivial read; updates the connection. Returns VerifyOut."""
    conn = store.get_connection(conn_id)
    checked_at = datetime.now(UTC)
    if conn is None:
        return VerifyOut(
            status="failed", account_id=None, arn=None, checked_at=checked_at, error="not found"
        ).model_dump(mode="json")
    forget_session(conn.id)
    try:
        identity = verify_session(resolve_session(conn))
    except CredentialError as e:
        conn.status = "failed"
        conn.last_error = str(e)[:500]
        conn.last_verified_at = checked_at
        store.save_connection(conn)
        return VerifyOut(
            status="failed", account_id=None, arn=None, checked_at=checked_at, error=conn.last_error
        ).model_dump(mode="json")
    conn.status = "connected"
    conn.account_id = identity["account_id"]
    conn.last_error = None
    conn.last_verified_at = checked_at
    store.save_connection(conn)
    return VerifyOut(
        status="connected",
        account_id=identity["account_id"],
        arn=identity["arn"],
        checked_at=checked_at,
        error=None,
    ).model_dump(mode="json")


__all__ = ["STOPPED_NOTE", "expire_stale", "new_job", "run_job", "verify_connection"]
