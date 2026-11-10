"""agent-worker: everything that reads a user's account with the READ-ONLY role.

Modes (event["mode"]):
  diagnosis         {"job_id"}        one diagnosis turn (async invoke from api-handler)
  verify            {"connection_id"} connection check (sync invoke from api-handler)
  recheck           {"proposal_id"}   remediation-flow: compare with the preview snapshot
  verify_proposal   {"proposal_id"}   remediation-flow: post-change verification
  expire            {"proposal_id"}   remediation-flow: the approval wait timed out
"""

import asyncio
import logging

from app.remediation import service
from app.storage.store import open_store
from app.worker import run_job, verify_connection

log = logging.getLogger(__name__)


def handler(event: dict, context=None) -> dict:
    mode = event.get("mode")
    if mode not in ("diagnosis", "verify", "recheck", "verify_proposal", "expire"):
        raise ValueError(f"Unknown agent-worker mode {mode!r}")
    if mode == "diagnosis":
        asyncio.run(run_job(event["job_id"], event["user_id"]))
        return {"ok": True}
    with open_store(event["user_id"]) as store:
        if mode == "verify":
            return verify_connection(store, event["connection_id"])
        if mode == "recheck":
            return service.recheck_step(store, event["proposal_id"])
        if mode == "verify_proposal":
            return service.verify_step(store, event["proposal_id"])
        if mode == "expire":
            return service.expire_step(store, event["proposal_id"])
    raise ValueError(f"Unknown agent-worker mode {mode!r}")
