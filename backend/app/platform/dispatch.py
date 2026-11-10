"""Hand background work to where it runs (docs/API_CONTRACT.md §9).

RUNTIME=local   everything runs in this FastAPI process (BackgroundTasks / direct calls).
RUNTIME=lambda  api-handler -> agent-worker (async Lambda invoke), connection verify (sync
                invoke), remediation-flow (Step Functions) with the user's decision sent by
                task token.

Uses the platform account's credentials (Lambda execution role / PLATFORM_AWS_PROFILE).
"""

import json
import logging
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import BackgroundTasks

from app.config import get_settings
from app.storage.models import Proposal

log = logging.getLogger(__name__)


class DispatchError(Exception):
    """The platform could not start the work (Lambda / Step Functions call failed)."""


def is_lambda() -> bool:
    return get_settings().runtime == "lambda"


@lru_cache
def _client(service: str):
    settings = get_settings()
    session = boto3.Session(profile_name=settings.platform_aws_profile or None)
    return session.client(service)


# ---- diagnosis jobs -------------------------------------------------------------------


def start_job(job_id: str, background: BackgroundTasks, user_id: str) -> None:
    if not is_lambda():
        from app.worker import run_job  # noqa: PLC0415 — avoids an import cycle

        background.add_task(run_job, job_id, user_id)
        return
    try:
        _client("lambda").invoke(
            FunctionName=get_settings().agent_worker_function,
            InvocationType="Event",  # async; the function is configured with 0 retries
            Payload=json.dumps(
                {"mode": "diagnosis", "job_id": job_id, "user_id": user_id}
            ).encode(),
        )
    except (ClientError, BotoCoreError) as e:
        raise DispatchError(f"Could not start agent-worker: {e}") from e


def verify_connection(conn_id: str, user_id: str) -> dict:
    """Run the connection check where the read-only AssumeRole is allowed (agent-worker)."""
    if not is_lambda():
        from app.storage.store import open_store  # noqa: PLC0415
        from app.worker import verify_connection as verify  # noqa: PLC0415

        with open_store(user_id) as store:
            return verify(store, conn_id)
    try:
        resp = _client("lambda").invoke(
            FunctionName=get_settings().agent_worker_function,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {"mode": "verify", "connection_id": conn_id, "user_id": user_id}
            ).encode(),
        )
    except (ClientError, BotoCoreError) as e:
        raise DispatchError(f"Could not reach agent-worker: {e}") from e
    payload = json.loads(resp["Payload"].read() or b"{}")
    if resp.get("FunctionError"):
        raise DispatchError(f"agent-worker failed: {payload.get('errorMessage', 'unknown')}")
    return payload


# ---- remediation-flow --------------------------------------------------------------------


def start_remediation_flow(p: Proposal) -> None:
    """One remediation-flow execution per proposal (RUNTIME=lambda; no-op locally)."""
    if not is_lambda():
        return
    settings = get_settings()
    preview = json.loads(p.preview_json or "{}")
    try:
        _client("stepfunctions").start_execution(
            stateMachineArn=settings.remediation_state_machine_arn,
            name=p.id,  # idempotent: the same proposal never starts twice
            input=json.dumps(
                {
                    "proposal_id": p.id,
                    "user_id": p.user_id,
                    "kind": p.kind,
                    "summary": preview.get("summary", p.action),
                    "link": f"{settings.frontend_url.rstrip('/')}/proposals",
                }
            ),
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ExecutionAlreadyExists":
            log.exception("Could not start remediation-flow for %s", p.id)
            raise DispatchError(f"Could not start remediation-flow: {e}") from e
    except BotoCoreError as e:
        raise DispatchError(f"Could not start remediation-flow: {e}") from e


def send_decision(p: Proposal | None) -> None:
    """Resume the approval wait of remediation-flow with the user's decision."""
    if not is_lambda() or p is None or not p.task_token:
        return  # locally the API runs the steps; on AWS the token may not be stored yet
    sfn = _client("stepfunctions")
    try:
        if p.status == "APPROVED":
            sfn.send_task_success(
                taskToken=p.task_token, output=json.dumps({"decision": "approve"})
            )
        elif p.status in ("REJECTED", "SUPERSEDED", "EXPIRED"):
            sfn.send_task_failure(
                taskToken=p.task_token, error=p.status, cause=f"Proposal {p.id} {p.status}"
            )
    except ClientError as e:
        # TaskTimedOut / InvalidToken: the wait already ended (decided twice, expired)
        log.info("Decision for %s not delivered: %s", p.id, e.response["Error"]["Code"])
