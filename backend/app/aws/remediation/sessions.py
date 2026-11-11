"""The write session used by the executor — locked to the API calls of ONE action.

- Role connections: AssumeRole into the connection's AutoAWSRemediation role (never the
  read-only role), same ExternalId, session name ``autoaws-fix-<proposal id>`` so the change is
  traceable in the user's CloudTrail.
- Access-key connections: only when REMEDIATION_ALLOW_ACCESS_KEYS is on (dev / LocalStack).

A botocore hook rejects every call outside the allow-list of the action (``write_actions``)
plus a few harmless reads the SDK may need, whatever the credentials could do.
"""

import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.aws.credentials import CredentialError, _new_session, platform_session
from app.aws.registry import iam_action
from app.config import get_settings
from app.storage.models import Connection

log = logging.getLogger(__name__)


class RemediationDisabled(Exception):
    """The connection has no way to execute approved changes."""


class RemediationViolation(Exception):
    """A call outside the approved action's allow-list was attempted."""


def remediation_enabled(conn: Connection) -> bool:
    if conn.type == "role":
        return bool(conn.remediation_role_arn)
    if conn.type == "access_key":
        return get_settings().remediation_allow_access_keys
    return False


def _guard(session: boto3.Session, allowed: set[str], proposal_id: str) -> boto3.Session:
    def check(model, **_) -> None:
        action = iam_action(model.service_model.service_name, model.name)
        if action not in allowed:
            log.error("Blocked %s while executing %s", action, proposal_id)
            raise RemediationViolation(f"Blocked {action}: not part of the approved action")

    session.events.register("before-call", check, unique_id=f"autoaws-fix-guard-{proposal_id}")
    return session


def remediation_session(
    conn: Connection, write_actions: list[str], proposal_id: str
) -> boto3.Session:
    """Session that can call only ``write_actions``. Raises RemediationDisabled."""
    if not remediation_enabled(conn):
        raise RemediationDisabled("Remediation is not enabled for this connection")
    settings = get_settings()
    if conn.type == "access_key":
        if not conn.access_key_id or not conn.secret_access_key:
            raise CredentialError("Connection has no access key stored")
        session = _new_session(
            aws_access_key_id=conn.access_key_id,
            aws_secret_access_key=conn.secret_access_key,
            region_name=conn.region,
        )
    else:
        try:
            creds = (
                platform_session()
                .client("sts")
                .assume_role(
                    RoleArn=conn.remediation_role_arn,
                    RoleSessionName=f"autoaws-fix-{proposal_id}"[:64],
                    ExternalId=conn.external_id or "",
                    DurationSeconds=settings.assume_role_duration_seconds,
                )["Credentials"]
            )
        except (ClientError, BotoCoreError) as e:
            raise CredentialError(f"AssumeRole of the remediation role failed: {e}") from e
        session = _new_session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=conn.region,
        )
    return _guard(session, set(write_actions), proposal_id)
