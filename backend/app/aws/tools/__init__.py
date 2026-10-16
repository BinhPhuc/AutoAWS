"""Importing this package registers every tool into app.aws.registry.REGISTRY."""

from app.aws.tools import cloudtrail, compute, dns, elb, logs, metrics, network  # noqa: F401
