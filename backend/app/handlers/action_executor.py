"""action-executor: the ONLY function that can assume AutoAWSRemediation (writes).

Modes (event["mode"]):
  store_token  {"proposal_id", "task_token"}  remediation-flow waits for the user's decision
  execute      {"proposal_id"}                run the approved action (locked write session)
"""

from app.remediation import service
from app.storage.store import open_store


def handler(event: dict, context=None) -> dict:
    mode = event.get("mode")
    with open_store() as store:
        if mode == "store_token":
            return service.store_task_token(store, event["proposal_id"], event["task_token"])
        if mode == "execute":
            return service.execute_step(store, event["proposal_id"])
    raise ValueError(f"Unknown action-executor mode {mode!r}")
