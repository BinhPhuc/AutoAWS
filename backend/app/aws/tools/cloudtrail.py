"""Change-history group: CloudTrail LookupEvents. STUB — planned for milestone M3.

TODO(M3): implement cloudtrail_lookup_events:
  - params: resource_name (e.g. subnet id / sg id), event_name, hours (<= 90 days)
  - LookupAttributes ResourceName / EventName; return event_time, event_name, username,
    resource ids, and a trimmed requestParameters (sanitized).
"""

import boto3

from app.aws.registry import tool

NOT_IMPLEMENTED = {"error": "NOT_IMPLEMENTED: CloudTrail tool is planned for M3"}


@tool(
    name="cloudtrail_lookup_events",
    group="cloudtrail",
    label="CloudTrail events",
    description="(Not implemented yet) Who changed what and when: management events for a "
    "resource (e.g. ReplaceRouteTableAssociation on a subnet).",
    input_schema={
        "type": "object",
        "properties": {
            "resource_name": {"type": "string"},
            "event_name": {"type": "string"},
            "hours": {"type": "integer", "minimum": 1, "maximum": 2160},
        },
    },
    aws_actions=["cloudtrail:LookupEvents"],
    stub=True,
)
def cloudtrail_lookup_events(session: boto3.Session, params: dict) -> dict:
    return dict(NOT_IMPLEMENTED)
