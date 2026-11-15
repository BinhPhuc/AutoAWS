"""Remediation actions by resource family; importing a module registers its actions."""

from app.aws.remediation.actions import (  # noqa: F401
    dns,
    elb,
    instance,
    nacl,
    routing,
    security_group,
)
