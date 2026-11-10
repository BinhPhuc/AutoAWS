"""Human-in-the-loop remediation: list proposals, decide, catalogue (API_CONTRACT.md §7).

Approving only records the decision; execution (re-check, write, verify) runs in a
background task with its own Store, and the client polls GET /proposals/{id}.
"""

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.schemas import DecisionIn, DecisionOut, ProposalOut, RemediationActionOut
from app.auth import User, current_user
from app.aws.remediation.catalog import CATALOG
from app.errors import AppError, NotFound
from app.platform import dispatch
from app.remediation.service import decide, execute_proposal, expire_due
from app.responses import ok
from app.storage.base import Store
from app.storage.store import get_store, open_store

router = APIRouter(tags=["remediation"])

_MESSAGES = {
    "approve": "Proposal approved",
    "reject": "Proposal rejected",
    "feedback": "Feedback sent",
}


def _get(store: Store, proposal_id: str, user: User):
    p = store.get_proposal(proposal_id)
    if p is None or p.user_id != user.id:
        raise NotFound("PROPOSAL_NOT_FOUND", "Proposal not found")
    return expire_due(store, p)


def _run(proposal_id: str) -> None:
    with open_store() as store:
        execute_proposal(store, proposal_id)


@router.get("/proposals")
def list_proposals(
    conversation_id: str | None = None,
    status: str | None = None,
    store: Store = Depends(get_store),
    user: User = Depends(current_user),
):
    proposals = [
        expire_due(store, p) for p in store.list_proposals(conversation_id, user_id=user.id)
    ]
    if status:
        proposals = [p for p in proposals if p.status == status]
    return ok([ProposalOut.from_model(p) for p in proposals])


@router.get("/proposals/{proposal_id}")
def get_proposal(
    proposal_id: str, store: Store = Depends(get_store), user: User = Depends(current_user)
):
    return ok(ProposalOut.from_model(_get(store, proposal_id, user)))


@router.post("/proposals/{proposal_id}/decision")
def decide_proposal(
    proposal_id: str,
    body: DecisionIn,
    background: BackgroundTasks,
    store: Store = Depends(get_store),
    user: User = Depends(current_user),
):
    if body.decision == "feedback" and not body.feedback.strip():
        raise AppError("VALIDATION_ERROR", 422, "Invalid request: feedback is required")
    proposal, followup = decide(
        store, _get(store, proposal_id, user), body.decision, body.feedback, by=user.id
    )
    if body.decision == "approve" and not dispatch.is_lambda():
        background.add_task(_run, proposal.id)  # on AWS remediation-flow runs the steps
    out = DecisionOut(proposal=ProposalOut.from_model(proposal), followup_question=followup)
    return ok(out, _MESSAGES[body.decision])


@router.get("/remediation/actions")
def list_actions():
    return ok(
        [
            RemediationActionOut(
                name=spec.name,
                label=spec.label,
                description=spec.description,
                input_schema=spec.input_schema,
                aws_actions=spec.write_actions,
            )
            for spec in CATALOG.values()
        ]
    )
