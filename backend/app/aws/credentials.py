"""Turn a Connection into a boto3 Session.

- access_key: direct session (dev only).
- role: platform session -> sts:AssumeRole(RoleArn, ExternalId) -> temporary session,
  cached in memory until shortly before the credentials expire. Temporary credentials
  are never written to the database or logs.
"""

import logging
from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.storage.models import Connection

log = logging.getLogger(__name__)

_role_cache: dict[str, tuple[boto3.Session, datetime]] = {}
_REFRESH_MARGIN = timedelta(seconds=60)


class CredentialError(Exception):
    """Raised when we cannot obtain usable credentials for a connection."""


def platform_session() -> boto3.Session:
    """Prefer credentials loaded from backend/.env; retain SDK fallback when unset."""
    settings = get_settings()
    key = settings.aws_access_key_id.get_secret_value()
    secret = settings.aws_secret_access_key.get_secret_value()
    token = settings.aws_session_token.get_secret_value()
    region = settings.aws_default_region or None
    if key or secret or token:
        if not key or not secret:
            raise CredentialError(
                "Set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in backend/.env"
            )
        return boto3.Session(
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            aws_session_token=token or None,
            region_name=region,
        )
    if settings.platform_aws_profile:
        return boto3.Session(profile_name=settings.platform_aws_profile, region_name=region)
    return boto3.Session(region_name=region)


def resolve_session(conn: Connection) -> boto3.Session:
    if conn.type == "access_key":
        if not conn.access_key_id or not conn.secret_access_key:
            raise CredentialError("Connection has no access key stored")
        return boto3.Session(
            aws_access_key_id=conn.access_key_id,
            aws_secret_access_key=conn.secret_access_key,
            region_name=conn.region,
        )

    if conn.type == "role":
        cached = _role_cache.get(conn.id)
        now = datetime.now(UTC)
        if cached and cached[1] - _REFRESH_MARGIN > now:
            return cached[0]
        if not conn.role_arn or not conn.external_id:
            raise CredentialError("Connection has no role ARN / external id")
        settings = get_settings()
        try:
            resp = (
                platform_session()
                .client("sts")
                .assume_role(
                    RoleArn=conn.role_arn,
                    RoleSessionName=f"autoaws-{conn.id}"[:64],
                    ExternalId=conn.external_id,
                    DurationSeconds=settings.assume_role_duration_seconds,
                )
            )
        except (ClientError, BotoCoreError) as e:
            raise CredentialError(f"AssumeRole failed: {e}") from e
        creds = resp["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=conn.region,
        )
        expiration = creds["Expiration"]
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=UTC)
        _role_cache[conn.id] = (session, expiration)
        return session

    raise CredentialError(f"Unknown connection type: {conn.type}")


def forget_session(conn_id: str) -> None:
    _role_cache.pop(conn_id, None)


def verify_session(session: boto3.Session) -> dict:
    """One identity call + one trivial read. Raises CredentialError on failure."""
    try:
        ident = session.client("sts").get_caller_identity()
        session.client("ec2").describe_regions(RegionNames=[session.region_name])
    except (ClientError, BotoCoreError) as e:
        raise CredentialError(str(e)) from e
    return {"account_id": ident["Account"], "arn": ident["Arn"]}
