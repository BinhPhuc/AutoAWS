"""Turn a Connection into a boto3 Session.

- access_key: direct session (dev only).
- role: platform session -> sts:AssumeRole(RoleArn, ExternalId) -> temporary session,
  cached in memory until shortly before the credentials expire. Temporary credentials
  are never written to the database or logs.

Every session handed to tools is guarded: a botocore hook rejects any operation that is
not read-only (``registry.is_read_only_action``), whatever the credentials would allow.
This matters most for access keys, where no IAM Deny backs us up.
"""

import logging
from datetime import UTC, datetime, timedelta

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.aws.registry import iam_action, is_read_only_action
from app.config import get_settings
from app.storage.models import Connection

log = logging.getLogger(__name__)

# Calls made by verify_session; the CloudFormation policy must allow them too.
VERIFY_AWS_ACTIONS = ["sts:GetCallerIdentity", "ec2:DescribeRegions"]

# Adaptive retries back off on throttling, e.g. CloudTrail LookupEvents allows ~2 calls/s
# per account and Region (docs/SYSTEM_OVERVIEW.md / report §2.3.2).
RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

_role_cache: dict[tuple[str, str], tuple[boto3.Session, datetime]] = {}
_REFRESH_MARGIN = timedelta(seconds=60)


class CredentialError(Exception):
    """Raised when we cannot obtain usable credentials for a connection."""


class ReadOnlyViolation(Exception):
    """A non read-only AWS operation was attempted on a user-account session."""


class _AwsSession(boto3.Session):
    """Session whose clients retry adaptively and, in dev, use a custom endpoint."""

    def __init__(self, *args, endpoint_url: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._endpoint_url = endpoint_url

    def client(self, *args, **kwargs):
        if self._endpoint_url:
            kwargs.setdefault("endpoint_url", self._endpoint_url)
        config = kwargs.get("config")
        kwargs["config"] = RETRY_CONFIG.merge(config) if config else RETRY_CONFIG
        return super().client(*args, **kwargs)


def _new_session(**kwargs) -> boto3.Session:
    return _AwsSession(endpoint_url=get_settings().aws_endpoint_url, **kwargs)


def _reject_non_read_only(model, **_) -> None:
    action = iam_action(model.service_model.service_name, model.name)
    if not is_read_only_action(action):
        log.error("Blocked non read-only AWS call %s", action)
        raise ReadOnlyViolation(f"Blocked non read-only AWS call: {action}")


def guard_read_only(session: boto3.Session) -> boto3.Session:
    """Make every client created from ``session`` afterwards unable to call writes."""
    session.events.register(
        "before-call", _reject_non_read_only, unique_id="autoaws-read-only-guard"
    )
    return session


def platform_session() -> boto3.Session:
    settings = get_settings()
    if settings.platform_aws_profile:
        return _new_session(profile_name=settings.platform_aws_profile)
    return _new_session()


def resolve_session(conn: Connection) -> boto3.Session:
    if conn.type == "access_key":
        if not conn.access_key_id or not conn.secret_access_key:
            raise CredentialError("Connection has no access key stored")
        return guard_read_only(
            _new_session(
                aws_access_key_id=conn.access_key_id,
                aws_secret_access_key=conn.secret_access_key,
                region_name=conn.region,
            )
        )

    if conn.type == "role":
        cached = _role_cache.get((conn.user_id, conn.id))
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
        session = guard_read_only(
            _new_session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=conn.region,
            )
        )
        expiration = creds["Expiration"]
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=UTC)
        _role_cache[(conn.user_id, conn.id)] = (session, expiration)
        return session

    raise CredentialError(f"Unknown connection type: {conn.type}")


def forget_session(conn_id: str, user_id: str = "local-dev") -> None:
    _role_cache.pop((user_id, conn_id), None)


def verify_session(session: boto3.Session) -> dict:
    """One identity call + one trivial read. Raises CredentialError on failure."""
    try:
        ident = session.client("sts").get_caller_identity()
        session.client("ec2").describe_regions(RegionNames=[session.region_name])
    except (ClientError, BotoCoreError) as e:
        raise CredentialError(str(e)) from e
    return {"account_id": ident["Account"], "arn": ident["Arn"]}
