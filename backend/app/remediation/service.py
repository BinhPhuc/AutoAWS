"""Proposal lifecycle: prepare -> wait for a decision -> re-check -> execute -> verify.

  PENDING_APPROVAL -> APPROVED -> EXECUTING -> SUCCEEDED
                   -> REJECTED | EXPIRED | SUPERSEDED (feedback)
  EXECUTING        -> STALE (resource changed since the preview, nothing written)
                   -> FAILED (the write call failed)
                   -> VERIFY_FAILED (+ a rollback proposal that must be approved too)
  rollback SUCCEEDED -> parent ROLLED_BACK

Every transition is a compare-and-set on the stored status and is appended to the
proposal's history (audit trail). Reads use the read-only session; writes only the
executor's session locked to the approved action (app.aws.remediation.sessions).
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jsonschema import Draft202012Validator

from app.agent.schemas import DiagnosisAnswer
from app.aws.credentials import CredentialError, resolve_session
from app.aws.remediation.catalog import ActionSpec, DryRunDenied, DryRunIgnored, get_action
from app.aws.remediation.sessions import (
    RemediationDisabled,
    remediation_enabled,
    remediation_session,
)
from app.config import get_settings
from app.errors import AppError
from app.platform import dispatch
from app.storage.base import Store
from app.storage.models import Connection, Conversation, Proposal, new_id, utcnow

log = logging.getLogger(__name__)

PENDING = "PENDING_APPROVAL"
APPROVED = "APPROVED"
EXECUTING = "EXECUTING"
SUCCEEDED = "SUCCEEDED"
REJECTED = "REJECTED"
EXPIRED = "EXPIRED"
SUPERSEDED = "SUPERSEDED"
STALE = "STALE"
FAILED = "FAILED"
VERIFY_FAILED = "VERIFY_FAILED"
ROLLED_BACK = "ROLLED_BACK"

MAX_PROPOSALS_PER_ANSWER = 5


def snapshot_hash(snapshot: dict) -> str:
    stable = {k: v for k, v in snapshot.items() if not k.startswith("_")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


def _history(p: Proposal) -> list[dict]:
    return json.loads(p.history_json or "[]")


def transition(
    store: Store, p: Proposal, to: str, note: str = "", expected: str | None = None, **fields
) -> bool:
    """Move ``p`` to ``to`` only if its stored status is still ``expected`` (default: the
    status ``p`` has now). Appends the change to the audit history."""
    expected = expected or p.status
    history = _history(p)
    history.append({"status": to, "at": utcnow().isoformat(), "note": note})
    p.status = to
    p.history_json = json.dumps(history, ensure_ascii=False)
    for key, value in fields.items():
        setattr(p, key, value)
    return store.update_proposal(p, expected_status=expected)


def expire_due(store: Store, p: Proposal) -> Proposal:
    due = p.status == PENDING and p.expires_at and _aware(p.expires_at) <= datetime.now(UTC)
    if due and transition(
        store, p, EXPIRED, "no decision within the approval window", expected=PENDING
    ):
        dispatch.send_decision(store.get_proposal(p.id))
    return p


def store_task_token(store: Store, proposal_id: str, task_token: str) -> dict:
    """remediation-flow is now waiting for the decision (action-executor). If the user
    already decided before the token was stored, deliver that decision right away."""
    store.set_proposal_token(proposal_id, task_token)
    p = store.get_proposal(proposal_id)
    if p is None:
        return {"ok": False, "status": "MISSING"}
    if p.status != PENDING:
        dispatch.send_decision(p)
    return {"ok": True, "status": p.status}


# ---- proposals from an answer ---------------------------------------------------------


@dataclass
class Prepared:
    spec: ActionSpec
    params: dict
    snapshot: dict
    preview: dict


def prepare(read_session, action: str, params: dict) -> tuple[Prepared | None, str | None]:
    """Validate + snapshot + pre-check with the READ-ONLY session. (prepared, error)."""
    spec = get_action(action)
    if spec is None:
        return None, f"Unknown remediation action {action!r}"
    errors = list(Draft202012Validator(spec.input_schema).iter_errors(params or {}))
    if errors:
        return None, f"Invalid parameters: {errors[0].message}"
    try:
        snapshot = spec.snapshot(read_session, params)
    except Exception as e:  # noqa: BLE001 — missing resource, AccessDenied, ...
        return None, f"Could not read the target resource: {type(e).__name__}: {e}"
    problem = spec.precheck(params, snapshot)
    if problem:
        return None, f"Pre-check failed: {problem}"
    return Prepared(spec, params, snapshot, spec.preview(params, snapshot)), None


def attach_proposals(
    store: Store,
    conversation: Conversation,
    message_id: str,
    conn: Connection | None,
    read_session,
    answer: DiagnosisAnswer,
) -> None:
    """Turn the answer's proposals into stored PENDING proposals (sets proposal_id / error)."""
    settings = get_settings()
    for i, ref in enumerate(answer.proposals):
        if conn is None:
            ref.error = "Connection not found"
            continue
        if not remediation_enabled(conn):
            ref.error = (
                "Remediation is not enabled for this connection: apply the fix steps yourself"
            )
            continue
        if i >= MAX_PROPOSALS_PER_ANSWER:
            ref.error = f"Too many proposals in one answer (max {MAX_PROPOSALS_PER_ANSWER})"
            continue
        prepared, error = prepare(read_session, ref.action, ref.params)
        if prepared is None:
            ref.error = error
            continue
        proposal = Proposal(
            id=new_id("prop"),
            conversation_id=conversation.id,
            message_id=message_id,
            connection_id=conn.id,
            action=ref.action,
            params_json=json.dumps(ref.params, ensure_ascii=False),
            reason=ref.reason,
            preview_json=json.dumps(prepared.preview, ensure_ascii=False, default=str),
            snapshot_json=json.dumps(prepared.snapshot, ensure_ascii=False, default=str),
            snapshot_hash=snapshot_hash(prepared.snapshot),
            expires_at=utcnow() + timedelta(hours=settings.proposal_ttl_hours),
            history_json=json.dumps(
                [{"status": PENDING, "at": utcnow().isoformat(), "note": "proposed by the agent"}]
            ),
        )
        store.create_proposal(proposal)
        dispatch.start_remediation_flow(proposal)
        ref.proposal_id = proposal.id


# ---- decisions ----------------------------------------------------------------------


def decide(
    store: Store, p: Proposal, decision: str, feedback: str = ""
) -> tuple[Proposal, str | None]:
    """Apply the user's decision. Returns (proposal, follow-up question for feedback)."""
    expire_due(store, p)
    if p.status != PENDING:
        raise AppError(
            "PROPOSAL_NOT_PENDING", 409, f"Proposal is not waiting for a decision ({p.status})"
        )
    if decision == "approve":
        conn = store.get_connection(p.connection_id)
        if conn is None or not remediation_enabled(conn):
            raise AppError(
                "REMEDIATION_DISABLED", 400, "Remediation is not enabled for this connection"
            )
        ok = transition(store, p, APPROVED, "approved by the user", expected=PENDING)
        followup = None
    elif decision == "reject":
        ok = transition(store, p, REJECTED, "rejected by the user", expected=PENDING)
        followup = None
    else:
        text = feedback.strip()
        ok = transition(store, p, SUPERSEDED, f"feedback: {text}", expected=PENDING)
        spec = get_action(p.action)
        label = spec.label if spec else p.action
        followup = (
            f'Góp ý cho đề xuất "{label}" ({p.id}): {text}\n'
            "Hãy xem lại và đề xuất lại cho phù hợp với góp ý này."
        )
    if not ok:
        raise AppError("PROPOSAL_NOT_PENDING", 409, "Proposal was decided by someone else")
    dispatch.send_decision(store.get_proposal(p.id))  # fresh: carries the stored task token
    return p, followup


# ---- execution (background, after approval) ------------------------------------------------


def execute_proposal(store: Store, proposal_id: str) -> None:
    """RUNTIME=local: re-check, execute and verify one APPROVED proposal. Never raises.
    (RUNTIME=lambda runs the same three steps as states of remediation-flow.)"""
    if recheck_step(store, proposal_id)["ok"] and execute_step(store, proposal_id)["ok"]:
        verify_step(store, proposal_id)


def _guarded(store: Store, proposal_id: str, step):
    """Run one step; any unexpected error ends the proposal in FAILED."""
    p = store.get_proposal(proposal_id)
    if p is None:
        return {"ok": False, "status": "MISSING"}
    try:
        return step(p)
    except Exception as e:  # noqa: BLE001 — the proposal must end in a final state
        log.exception("Proposal %s failed", p.id)
        transition(store, p, FAILED, "unexpected error", error=f"{type(e).__name__}: {e}")
        return {"ok": False, "status": FAILED}


def _context(store: Store, p: Proposal):
    spec = get_action(p.action)
    conn = store.get_connection(p.connection_id)
    parent = store.get_proposal(p.parent_id) if p.kind == "rollback" and p.parent_id else None
    return spec, conn, json.loads(p.params_json), parent


def _note(store: Store, p: Proposal, note: str) -> None:
    """Add an audit entry without changing the status."""
    history = _history(p)
    history.append({"status": p.status, "at": utcnow().isoformat(), "note": note})
    p.history_json = json.dumps(history, ensure_ascii=False)
    store.update_proposal(p)


def recover_interrupted(store: Store) -> list[str]:
    """RUNTIME=local, at startup: proposals the previous process left mid-way.

    APPROVED (nothing written yet) is executed again; EXECUTING with a stored result is
    verified; EXECUTING without one may or may not have been applied, so it ends FAILED
    with a note to check the resource (never written twice). Returns the ids handled."""
    handled = []
    for status in (APPROVED, EXECUTING):
        for p in store.list_proposals(status=status):
            handled.append(p.id)
            if p.status == APPROVED:
                execute_proposal(store, p.id)
            elif p.result_json is not None:
                verify_step(store, p.id)
            else:
                transition(
                    store,
                    p,
                    FAILED,
                    "interrupted while applying the change (backend restarted)",
                    error="Interrupted: the change may or may not have been applied — check "
                    "the resource, then ask again",
                )
    return handled


def recheck_step(store: Store, proposal_id: str) -> dict:
    """APPROVED -> EXECUTING, then compare the resource with the preview snapshot (read-only).
    Runs in agent-worker on AWS."""

    def step(p: Proposal) -> dict:
        if p.status == APPROVED and not transition(
            store, p, EXECUTING, "re-checking the resource", expected=APPROVED
        ):
            return {"ok": False, "status": p.status}
        if p.status != EXECUTING:
            return {"ok": False, "status": p.status}
        spec, conn, params, parent = _context(store, p)
        if spec is None or conn is None:
            transition(store, p, FAILED, "action or connection no longer exists")
            return {"ok": False, "status": FAILED}
        if p.kind == "rollback" and parent is None:
            transition(store, p, FAILED, "the proposal to roll back no longer exists")
            return {"ok": False, "status": FAILED}
        try:
            current = spec.snapshot(resolve_session(conn), params)
        except Exception as e:  # noqa: BLE001
            transition(store, p, FAILED, "could not re-read the resource", error=str(e))
            return {"ok": False, "status": FAILED}
        if snapshot_hash(current) != p.snapshot_hash:
            transition(
                store,
                p,
                STALE,
                "the resource changed since the preview; nothing was changed",
                error="Resource changed since the preview — propose again",
            )
            return {"ok": False, "status": STALE}
        return {"ok": True, "status": EXECUTING}

    return _guarded(store, proposal_id, step)


def execute_step(store: Store, proposal_id: str) -> dict:
    """The only write: the approved action through the locked write session. Runs in
    action-executor on AWS. Idempotent: a retried step does not write twice."""

    def step(p: Proposal) -> dict:
        if p.status != EXECUTING:
            return {"ok": False, "status": p.status}
        if p.result_json is not None:  # already executed (Step Functions retry)
            return {"ok": True, "status": EXECUTING}
        spec, conn, params, parent = _context(store, p)
        read = resolve_session(conn)
        snapshot = json.loads(p.snapshot_json)
        try:
            write = remediation_session(conn, spec.write_actions, p.id)
            if p.kind == "fix" and spec.dry_run and get_settings().dry_run_enabled:
                try:
                    spec.dry_run(read, write, params, snapshot)
                except DryRunDenied as e:
                    transition(store, p, FAILED, "dry run refused", error=f"Permission: {e}")
                    return {"ok": False, "status": FAILED}
                except DryRunIgnored as e:
                    transition(store, p, FAILED, "dry run not honoured", error=str(e))
                    return {"ok": False, "status": FAILED}
                _note(store, p, "dry run passed")
            if p.kind == "fix":
                result = spec.execute(read, write, params, snapshot)
            else:
                spec.undo(
                    read,
                    write,
                    params,
                    json.loads(parent.snapshot_json),
                    json.loads(parent.result_json or "{}"),
                )
                result = {}
        except (RemediationDisabled, CredentialError) as e:
            transition(store, p, FAILED, "no write access", error=str(e))
            return {"ok": False, "status": FAILED}
        except Exception as e:  # noqa: BLE001 — AWS rejected the change
            transition(
                store, p, FAILED, "the change was rejected", error=f"{type(e).__name__}: {e}"
            )
            return {"ok": False, "status": FAILED}
        p.result_json = json.dumps(result, default=str)
        store.update_proposal(p)
        return {"ok": True, "status": EXECUTING}

    return _guarded(store, proposal_id, step)


def verify_step(store: Store, proposal_id: str) -> dict:
    """Read the resource again (read-only) and check the action's post-condition.
    Runs in agent-worker on AWS. A failed check proposes a rollback (needs approval)."""

    def step(p: Proposal) -> dict:
        if p.status != EXECUTING or p.result_json is None:
            return {"ok": False, "status": p.status}
        spec, conn, params, parent = _context(store, p)
        read = resolve_session(conn)
        snapshot = json.loads(p.snapshot_json)
        result = json.loads(p.result_json)
        if p.kind == "fix":
            ok, details = spec.verify(read, params, snapshot, result)
            verification = json.dumps({"ok": ok, "details": details}, ensure_ascii=False)
            if ok:
                transition(store, p, SUCCEEDED, "verified", verification_json=verification)
                return {"ok": True, "status": SUCCEEDED}
            transition(
                store, p, VERIFY_FAILED, "verification failed", verification_json=verification
            )
            rollback = _propose_rollback(store, p, spec, read, params)
            return {"ok": False, "status": VERIFY_FAILED, "rollback_id": rollback}
        after = spec.snapshot(read, params)
        restored = snapshot_hash(after) == parent.snapshot_hash
        details = (
            "state matches the one before the change"
            if restored
            else "state differs from the one before the change"
        )
        verification = json.dumps({"ok": restored, "details": details})
        if restored:
            transition(
                store, p, SUCCEEDED, "rolled back and verified", verification_json=verification
            )
            transition(store, parent, ROLLED_BACK, f"rolled back by {p.id}")
            return {"ok": True, "status": SUCCEEDED}
        transition(store, p, VERIFY_FAILED, "rollback not verified", verification_json=verification)
        return {"ok": False, "status": VERIFY_FAILED}

    return _guarded(store, proposal_id, step)


def expire_step(store: Store, proposal_id: str) -> dict:
    """The approval wait timed out (remediation-flow)."""
    p = store.get_proposal(proposal_id)
    if p is not None and p.status == PENDING:
        transition(store, p, EXPIRED, "no decision within the approval window", expected=PENDING)
    return {"ok": True, "status": p.status if p else "MISSING"}


def _propose_rollback(
    store: Store, p: Proposal, spec: ActionSpec, read, params: dict
) -> str | None:
    try:
        after = spec.snapshot(read, params)
    except Exception:  # noqa: BLE001
        log.exception("Could not snapshot %s for its rollback", p.id)
        return None
    undo = spec.undo_description(params, json.loads(p.snapshot_json))
    rollback = Proposal(
        id=new_id("prop"),
        conversation_id=p.conversation_id,
        message_id=p.message_id,
        connection_id=p.connection_id,
        kind="rollback",
        parent_id=p.id,
        action=p.action,
        params_json=p.params_json,
        reason="Kiểm chứng sau khi sửa không đạt: đề xuất hoàn tác về trạng thái trước.",
        preview_json=json.dumps(
            {
                "summary": f"Undo {p.id}: {undo}",
                "changes": [],
                "impact": "Restores the state captured before the approved change.",
                "risk": "low",
                "rollback": "-",
                "verify": "The resource matches the state before the change.",
            }
        ),
        snapshot_json=json.dumps(after, default=str),
        snapshot_hash=snapshot_hash(after),
        expires_at=utcnow() + timedelta(hours=get_settings().proposal_ttl_hours),
        history_json=json.dumps(
            [{"status": PENDING, "at": utcnow().isoformat(), "note": f"rollback of {p.id}"}]
        ),
    )
    store.create_proposal(rollback)
    dispatch.start_remediation_flow(rollback)
    return rollback.id
