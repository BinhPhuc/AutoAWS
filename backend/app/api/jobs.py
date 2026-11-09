"""Background diagnosis jobs: poll and cancel (docs/API_CONTRACT.md §8)."""

from fastapi import APIRouter, Depends

from app.api.schemas import JobOut
from app.errors import NotFound
from app.responses import ok
from app.storage.base import Store
from app.storage.store import get_store
from app.worker import ACTIVE, expire_stale

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get(store: Store, job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise NotFound("JOB_NOT_FOUND", "Job not found")
    return expire_stale(store, job)


@router.get("/{job_id}")
def get_job(job_id: str, after: int = -1, store: Store = Depends(get_store)):
    return ok(JobOut.from_model(_get(store, job_id), after=after))


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, store: Store = Depends(get_store)):
    job = _get(store, job_id)
    if job.status in ACTIVE:
        store.update_job(job.id, cancel_requested=True)
        job = store.get_job(job.id) or job
    return ok(JobOut.from_model(job), "Cancel requested")
