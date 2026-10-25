"""Deterministic local demonstration data, never an AWS observation."""

import boto3

from app.aws.registry import tool


@tool(
    name="demo_instance_status",
    group="compute",
    label="Demo instance status (simulated)",
    description="Return simulated instance state for a local demonstration, not real AWS data.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    aws_actions=[],
)
def demo_instance_status(session: boto3.Session, params: dict) -> dict:
    if params:
        return {"error": "This demo tool accepts no parameters"}
    return {"simulated": True, "instance_id": "demo-instance", "state": "stopped"}
