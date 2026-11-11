import re
import secrets

from fastapi import APIRouter, Depends

from app.api.schemas import (
    CloudFormationOut,
    CloudFormationPreviewIn,
    ConnectionIn,
    ConnectionOut,
    ConnectionPatch,
    VerifyOut,
)
from app.auth import User, current_user
from app.aws import cloudformation
from app.aws.credentials import forget_session
from app.config import get_settings
from app.errors import AppError, NotFound
from app.platform import dispatch
from app.responses import ok
from app.storage.base import Store
from app.storage.models import Connection
from app.storage.store import get_store

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/setup")
def connection_setup(user: User = Depends(current_user)):
    settings = get_settings()
    account = settings.platform_aws_account_id.strip()
    valid_account = bool(re.fullmatch(r"[0-9]{12}", account))
    principals = list(
        dict.fromkeys(
            arn
            for arn in (settings.platform_agent_role_arn, settings.platform_executor_role_arn)
            if arn
        )
    )
    return ok(
        {
            "account_id": account if valid_account else None,
            "role_name": cloudformation.ROLE_NAME,
            "trust_principals": principals
            or ([f"arn:aws:iam::{account}:root"] if valid_account else []),
        }
    )


@router.post("/cloudformation-preview")
def preview_cloudformation(body: CloudFormationPreviewIn, user: User = Depends(current_user)):
    settings = get_settings()
    account = settings.platform_aws_account_id.strip()
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
            template_yaml=cloudformation.render_template(
                account,
                body.external_id,
                agent_role_arn=settings.platform_agent_role_arn,
                executor_role_arn=settings.platform_executor_role_arn,
            ),
        )
    )


def _get(store: Store, conn_id: str, user: User) -> Connection:
    conn = store.get_connection(conn_id)
    if conn is None or conn.user_id != user.id:  # someone else's: as if it did not exist
        raise NotFound("CONNECTION_NOT_FOUND", "Connection not found")
    return conn


@router.post("")
def create_connection(
    body: ConnectionIn, store: Store = Depends(get_store), user: User = Depends(current_user)
):
    if body.type == "access_key":
        conn = Connection(
            user_id=user.id,
            name=body.name,
            type="access_key",
            region=body.region,
            access_key_id=body.access_key_id,
            secret_access_key=body.secret_access_key,
        )
    else:
        conn = Connection(
            user_id=user.id,
            name=body.name,
            type="role",
            region=body.region,
            role_arn=body.role_arn,
            # Preserve the value used to create the role's trust policy during setup.
            external_id=body.external_id or f"autoaws-{secrets.token_hex(12)}",
            remediation_role_arn=body.remediation_role_arn,
        )
    store.create_connection(conn)
    return ok(ConnectionOut.from_model(conn), "Connection created", 201)


@router.get("")
def list_connections(store: Store = Depends(get_store), user: User = Depends(current_user)):
    return ok([ConnectionOut.from_model(c) for c in store.list_connections(user.id)])


@router.get("/{conn_id}")
def get_connection(
    conn_id: str, store: Store = Depends(get_store), user: User = Depends(current_user)
):
    return ok(ConnectionOut.from_model(_get(store, conn_id, user)))


@router.patch("/{conn_id}")
def update_connection(
    conn_id: str,
    body: ConnectionPatch,
    store: Store = Depends(get_store),
    user: User = Depends(current_user),
):
    conn = _get(store, conn_id, user)
    if conn.type != "role":
        raise AppError(
            "VALIDATION_ERROR", 400, "A remediation role can only be set on role connections"
        )
    conn.remediation_role_arn = body.remediation_role_arn
    store.save_connection(conn)
    return ok(ConnectionOut.from_model(conn), "Connection updated")


@router.delete("/{conn_id}")
def delete_connection(
    conn_id: str, store: Store = Depends(get_store), user: User = Depends(current_user)
):
    conn = _get(store, conn_id, user)
    forget_session(conn.id)
    store.delete_connection(conn)
    return ok(None, "Connection deleted")


@router.post("/{conn_id}/verify")
def verify_connection(
    conn_id: str, store: Store = Depends(get_store), user: User = Depends(current_user)
):
    _get(store, conn_id, user)
    try:
        result = VerifyOut.model_validate(dispatch.verify_connection(conn_id))
    except dispatch.DispatchError as e:
        raise AppError("INTERNAL", 500, "Could not verify the connection") from e
    message = (
        "Connection verified"
        if result.status == "connected"
        else ("Connection verification failed")
    )
    return ok(result, message)


@router.get("/{conn_id}/cloudformation")
def get_cloudformation(
    conn_id: str, store: Store = Depends(get_store), user: User = Depends(current_user)
):
    conn = _get(store, conn_id, user)
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
        template_yaml=cloudformation.render_template(
            platform_account,
            conn.external_id or "",
            agent_role_arn=get_settings().platform_agent_role_arn,
            executor_role_arn=get_settings().platform_executor_role_arn,
        ),
    )
    return ok(out)
