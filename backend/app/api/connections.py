import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.schemas import (
    CloudFormationOut,
    CloudFormationPreviewIn,
    ConnectionIn,
    ConnectionOut,
    VerifyOut,
)
from app.aws import cloudformation
from app.aws.credentials import CredentialError, forget_session, resolve_session, verify_session
from app.config import get_settings
from app.errors import AppError, NotFound
from app.responses import ok
from app.storage import repo
from app.storage.db import get_session
from app.storage.models import Connection

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/setup")
def connection_setup():
    account = get_settings().platform_aws_account_id.strip()
    return ok(
        {
            "account_id": account if re.fullmatch(r"[0-9]{12}", account) else None,
            "role_name": cloudformation.ROLE_NAME,
        }
    )


@router.post("/cloudformation-preview")
def preview_cloudformation(body: CloudFormationPreviewIn):
    account = get_settings().platform_aws_account_id.strip()
    if not re.fullmatch(r"[0-9]{12}", account):
        raise AppError(
            "CONNECTION_SETUP_UNAVAILABLE", 503, "Connection setup is temporarily unavailable"
        )
    return ok(
        CloudFormationOut(
            stack_name=cloudformation.STACK_NAME,
            role_name=cloudformation.ROLE_NAME,
            external_id=body.external_id,
            platform_account_id=account,
            template_yaml=cloudformation.render_template(account, body.external_id),
        )
    )


def _get(db: Session, conn_id: str) -> Connection:
    conn = repo.get_connection(db, conn_id)
    if conn is None:
        raise NotFound("CONNECTION_NOT_FOUND", "Connection not found")
    return conn


@router.post("")
def create_connection(body: ConnectionIn, db: Session = Depends(get_session)):
    if body.type == "access_key":
        conn = Connection(
            name=body.name,
            type="access_key",
            region=body.region,
            access_key_id=body.access_key_id,
            secret_access_key=body.secret_access_key,
        )
    else:
        conn = Connection(
            name=body.name,
            type="role",
            region=body.region,
            role_arn=body.role_arn,
            external_id=body.external_id or f"autoaws-{secrets.token_hex(12)}",
        )
    repo.create_connection(db, conn)
    return ok(ConnectionOut.from_model(conn), "Connection created", 201)


@router.get("")
def list_connections(db: Session = Depends(get_session)):
    return ok([ConnectionOut.from_model(c) for c in repo.list_connections(db)])


@router.get("/{conn_id}")
def get_connection(conn_id: str, db: Session = Depends(get_session)):
    return ok(ConnectionOut.from_model(_get(db, conn_id)))


@router.delete("/{conn_id}")
def delete_connection(conn_id: str, db: Session = Depends(get_session)):
    conn = _get(db, conn_id)
    forget_session(conn.id)
    repo.delete_connection(db, conn)
    return ok(None, "Connection deleted")


@router.post("/{conn_id}/verify")
def verify_connection(conn_id: str, db: Session = Depends(get_session)):
    conn = _get(db, conn_id)
    forget_session(conn.id)
    checked_at = datetime.now(UTC)
    try:
        identity = verify_session(resolve_session(conn))
    except CredentialError as e:
        conn.status = "failed"
        conn.last_error = str(e)[:500]
        conn.last_verified_at = checked_at
        repo.save(db, conn)
        result = VerifyOut(
            status="failed", account_id=None, arn=None, checked_at=checked_at, error=conn.last_error
        )
        return ok(result, "Connection verification failed")

    conn.status = "connected"
    conn.account_id = identity["account_id"]
    conn.last_error = None
    conn.last_verified_at = checked_at
    repo.save(db, conn)
    result = VerifyOut(
        status="connected",
        account_id=identity["account_id"],
        arn=identity["arn"],
        checked_at=checked_at,
        error=None,
    )
    return ok(result, "Connection verified")


@router.get("/{conn_id}/cloudformation")
def get_cloudformation(conn_id: str, db: Session = Depends(get_session)):
    conn = _get(db, conn_id)
    if conn.type != "role":
        raise AppError(
            "VALIDATION_ERROR",
            400,
            "CloudFormation template is only available for role connections",
        )
    platform_account = get_settings().platform_aws_account_id or "<PLATFORM_ACCOUNT_ID>"
    out = CloudFormationOut(
        stack_name=cloudformation.STACK_NAME,
        role_name=cloudformation.ROLE_NAME,
        external_id=conn.external_id or "",
        platform_account_id=platform_account,
        template_yaml=cloudformation.render_template(platform_account, conn.external_id or ""),
    )
    return ok(out)
