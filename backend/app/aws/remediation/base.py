"""Building blocks of the remediation catalogue (docs/API_CONTRACT.md §7).

Each action is plain code:

  snapshot(read, params)                      -> state of the target (read-only session)
  precheck(params, snapshot)                  -> problem text, or None
  preview(params, snapshot)                   -> what the user sees before approving
  execute(read, write, params, snapshot)      -> result (ids needed for undo)
  verify(read, params, snapshot, result)      -> (ok, details)
  undo(read, write, params, snapshot, result) -> None (back to the snapshot state);
                                                 None when there is no automatic undo

Snapshot keys starting with "_" are display-only: they are not part of the hash used for the
STALE check and to confirm an undo restored the original state.

Writes happen only through ``write`` (a session locked to ``write_actions``); every read goes
through the read-only session. No action deletes a user's resource, touches IAM or stops an
instance; removing a rule / route / entry / target is a configuration change that the
snapshot can restore.
"""

import ipaddress
import time
from collections.abc import Callable
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

Session = boto3.Session

# Ports never opened to the whole Internet, whatever the model proposes.
SENSITIVE_PORTS = (22, 3389)
WORLD = {"0.0.0.0/0", "::/0"}


@dataclass(frozen=True)
class ActionSpec:
    name: str
    group: str  # resource family, for the prompt and the docs
    label: str
    description: str  # for the LLM
    input_schema: dict
    write_actions: list[str]  # what the AutoAWSRemediation role grants
    snapshot: Callable[[Session, dict], dict]
    precheck: Callable[[dict, dict], str | None]
    preview: Callable[[dict, dict], dict]
    execute: Callable[[Session, Session, dict, dict], dict]
    verify: Callable[[Session, dict, dict, dict], tuple[bool, str]]
    # None: no automatic undo (e.g. starting an instance: AutoAWS never stops one)
    undo: Callable[[Session, Session, dict, dict, dict], None] | None = None
    undo_description: Callable[[dict, dict], str] = lambda p, s: ""
    # The same write call with DryRun=True (EC2 only): permission check, nothing changes
    dry_run: Callable[[Session, Session, dict, dict], None] | None = None


class DryRunDenied(Exception):
    """AWS refused the dry run: the remediation role lacks the permission."""


class DryRunIgnored(Exception):
    """The endpoint did not answer DryRunOperation: it may have applied the change
    (emulators such as moto / LocalStack ignore DryRun on some EC2 calls)."""


def expect_dry_run(call: Callable[..., object], **kwargs) -> None:
    """Run ``call(DryRun=True, **kwargs)``; AWS answers with error DryRunOperation when the
    request would have succeeded. Anything else stops the execution."""
    try:
        call(DryRun=True, **kwargs)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "DryRunOperation":
            return
        if code in ("UnauthorizedOperation", "AccessDenied", "AccessDeniedException"):
            raise DryRunDenied(e.response.get("Error", {}).get("Message", code)) from e
        raise
    raise DryRunIgnored("the endpoint ignored DryRun; stopping before any further write")


CATALOG: dict[str, ActionSpec] = {}

# Read calls the actions make outside the read tools (added to the read-only role policy).
EXTRA_READ_ACTIONS: list[str] = []


def register(spec: ActionSpec, extra_reads: tuple[str, ...] = ()) -> ActionSpec:
    if spec.name in CATALOG:
        raise ValueError(f"Duplicate remediation action {spec.name}")
    CATALOG[spec.name] = spec
    for action in extra_reads:
        if action not in EXTRA_READ_ACTIONS:
            EXTRA_READ_ACTIONS.append(action)
    return spec


def get_action(name: str) -> ActionSpec | None:
    return CATALOG.get(name)


def all_write_actions() -> list[str]:
    return sorted({a for spec in CATALOG.values() for a in spec.write_actions})


def preview(summary, changes, impact, risk, rollback, verify) -> dict:
    return {
        "summary": summary,
        "changes": changes,
        "impact": impact,
        "risk": risk,
        "rollback": rollback,
        "verify": verify,
    }


def wait_until(check: Callable[[], tuple[bool, str]]) -> tuple[bool, str]:
    """Poll ``check`` until it passes or the verification timeout runs out."""
    settings = get_settings()
    deadline = time.monotonic() + settings.remediation_verify_timeout_seconds
    while True:
        ok, details = check()
        if ok or time.monotonic() >= deadline:
            return ok, details
        time.sleep(settings.remediation_verify_poll_seconds)


# ---- shared checks -----------------------------------------------------------------


def network(cidr: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(cidr, strict=False)


def is_world(cidr: str | None) -> bool:
    if not cidr:
        return False
    try:
        return str(network(cidr)) in WORLD
    except ValueError:
        return False


def opens_sensitive_port(protocol: str, from_port: int | None, to_port: int | None) -> bool:
    """Does the port range of a rule contain SSH / RDP? ``all`` always does."""
    if protocol == "all":
        return True
    if protocol not in ("tcp", "udp") or from_port is None:
        return False
    high = from_port if to_port is None else to_port
    return any(from_port <= port <= high for port in SENSITIVE_PORTS)


def port_problem(protocol: str, from_port: int | None, to_port: int | None) -> str | None:
    """Ports are required (and ordered) for tcp / udp."""
    if protocol in ("tcp", "udp"):
        if from_port is None:
            return f"from_port is required for {protocol}"
        if from_port < 0 or (to_port is not None and to_port < 0):
            return f"{protocol} ports must be between 0 and 65535"
        if to_port is not None and to_port < from_port:
            return f"to_port {to_port} is lower than from_port {from_port}"
    return None


def cidr_problem(cidr: str) -> str | None:
    try:
        network(cidr)
    except ValueError:
        return f"{cidr} is not a valid CIDR"
    return None


PORT = {"type": "integer", "minimum": -1, "maximum": 65535}
PROTOCOL = {"type": "string", "enum": ["tcp", "udp", "icmp", "all"]}
DIRECTION = {"type": "string", "enum": ["ingress", "egress"]}
