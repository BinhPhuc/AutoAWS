"""Fixed, generic catalogue of remediation actions (docs/API_CONTRACT.md §7).

Actions are grouped by resource and operation (security group rules, routes, network ACL
entries, subnet / instance settings, Elastic IPs, Route 53 records, target groups), not by
incident: each one is a small, reviewable change with its own snapshot, pre-check, preview,
execute, verify and undo (``app.aws.remediation.base``). Importing this module registers
every action of ``app.aws.remediation.actions``.
"""

from app.aws.remediation import actions  # noqa: F401  (registers the catalogue)
from app.aws.remediation.base import (
    CATALOG,
    EXTRA_READ_ACTIONS,
    ActionSpec,
    DryRunDenied,
    DryRunIgnored,
    all_write_actions,
    expect_dry_run,
    get_action,
)

__all__ = [
    "CATALOG",
    "EXTRA_READ_ACTIONS",
    "ActionSpec",
    "DryRunDenied",
    "DryRunIgnored",
    "all_write_actions",
    "expect_dry_run",
    "get_action",
]
