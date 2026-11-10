import secrets

from fastapi import APIRouter, Depends

from app.api.schemas import (
    CloudFormationOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionPatch,
    VerifyOut,
)
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


def _get(store: Store, conn_id: str) -> Connection:
    conn = store.get_connection(conn_id)
    if conn is None:
        raise NotFound("CONNECTION_NOT_FOUND", "Connection not found")
    return conn


@router.post("")
def create_connection(body: ConnectionIn, store: Store = Depends(get_store)):
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
            remediation_role_arn=body.remediation_role_arn,
        )
    store.create_connection(conn)
    return ok(ConnectionOut.from_model(conn), "Connection created", 201)


@router.get("")
def list_connections(store: Store = Depends(get_store)):
    return ok([ConnectionOut.from_model(c) for c in store.list_connections()])


@router.get("/{conn_id}")
def get_connection(conn_id: str, store: Store = Depends(get_store)):
    return ok(ConnectionOut.from_model(_get(store, conn_id)))


@router.patch("/{conn_id}")
def update_connection(conn_id: str, body: ConnectionPatch, store: Store = Depends(get_store)):
    conn = _get(store, conn_id)
    if conn.type != "role":
        raise AppError(
            "VALIDATION_ERROR", 400, "A remediation role can only be set on role connections"
        )
    conn.remediation_role_arn = body.remediation_role_arn
    store.save_connection(conn)
    return ok(ConnectionOut.from_model(conn), "Connection updated")


@router.delete("/{conn_id}")
def delete_connection(conn_id: str, store: Store = Depends(get_store)):
    conn = _get(store, conn_id)
    forget_session(conn.id, conn.user_id)
    store.delete_connection(conn)
    return ok(None, "Connection deleted")


@router.post("/{conn_id}/verify")
def verify_connection(conn_id: str, store: Store = Depends(get_store)):
    _get(store, conn_id)
    try:
        result = VerifyOut.model_validate(dispatch.verify_connection(conn_id, store.user_id))
    except dispatch.DispatchError as e:
        raise AppError("INTERNAL", 500, "Could not verify the connection") from e
    message = (
        "Connection verified"
        if result.status == "connected"
        else ("Connection verification failed")
    )
    return ok(result, message)


@router.get("/{conn_id}/cloudformation")
def get_cloudformation(conn_id: str, store: Store = Depends(get_store)):
    conn = _get(store, conn_id)
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
