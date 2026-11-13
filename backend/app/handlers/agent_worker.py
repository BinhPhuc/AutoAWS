"""agent-worker: everything that reads a user's account with the READ-ONLY role.

Modes (event["mode"]):
  diagnosis         {"job_id"}        one diagnosis turn (async invoke from api-handler)
  verify            {"connection_id"} connection check (sync invoke from api-handler)
  recheck           {"proposal_id"}   remediation-flow: compare with the preview snapshot
  verify_proposal   {"proposal_id"}   remediation-flow: post-change verification
  expire            {"proposal_id"}   remediation-flow: the approval wait timed out
  revise            {"proposal_id", "params", "by"}  user-edited parameters -> new proposal
  rollback          {"proposal_id", "by"}  the user asks to undo an applied fix
  llm_test          {}                one short request to the saved LLM (admin page)
                                    (both: sync invoke from api-handler; errors come back as data)
"""

import asyncio
import logging

from app.errors import AppError
from app.remediation import service
from app.storage.store import open_store
from app.worker import run_job, verify_connection

log = logging.getLogger(__name__)


def handler(event: dict, context=None) -> dict:
    mode = event.get("mode")
    if mode == "diagnosis":
        asyncio.run(run_job(event["job_id"]))
        return {"ok": True}
    with open_store() as store:
        if mode == "verify":
            return verify_connection(store, event["connection_id"])
        if mode == "recheck":
            return service.recheck_step(store, event["proposal_id"])
        if mode == "verify_proposal":
            return service.verify_step(store, event["proposal_id"])
        if mode == "expire":
            return service.expire_step(store, event["proposal_id"])
        if mode == "llm_test":
            from app.llm.check import test_llm  # noqa: PLC0415
            from app.llm.config_store import effective_settings, forget_cache  # noqa: PLC0415

            forget_cache()  # the admin just saved: read the latest settings
            return asyncio.run(test_llm(effective_settings()))
        if mode in ("revise", "rollback"):
            try:
                if mode == "revise":
                    new = service.revise(
                        store, event["proposal_id"], event["params"], by=event["by"]
                    )
                else:
                    new = service.request_rollback(store, event["proposal_id"], by=event["by"])
            except AppError as e:
                return {"ok": False, "error": e.error, "status": e.status, "message": e.message}
            return {"ok": True, "proposal_id": new.id}
    raise ValueError(f"Unknown agent-worker mode {mode!r}")
