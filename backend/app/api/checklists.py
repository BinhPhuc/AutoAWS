"""Checklist runner — out of scope for the init phase (docs/BACKEND_PLAN.md §6).

TODO: POST /checklists/runs {connection_id, items[]} -> run each item through the agent,
persist per-item results, GET /checklists/runs/{id} for progress.
"""

from fastapi import APIRouter

from app.errors import AppError

router = APIRouter(prefix="/checklists", tags=["checklists"])


@router.post("/runs")
def start_run():
    raise AppError("NOT_IMPLEMENTED", 501, "Checklist runs are not available yet")
