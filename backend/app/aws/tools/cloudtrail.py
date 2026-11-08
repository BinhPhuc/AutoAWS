"""Change-history group: CloudTrail LookupEvents (management events, last 90 days).

LookupEvents filters by ONE lookup attribute per call and allows about 2 calls per second
per account and Region; the session retries adaptively (app.aws.credentials) and the
tool reads at most a few pages.
"""

import json

import boto3

from app.aws.registry import tool
from app.aws.tools._common import ISO_TIME_SCHEMA, hours_schema, iso, time_window, window

# tool parameter -> LookupAttributes key
LOOKUP_KEYS = {
    "resource_name": "ResourceName",
    "event_name": "EventName",
    "username": "Username",
    "event_source": "EventSource",
}
MAX_PAGES = 5
REQUEST_PARAMS_CHARS = 800


def _trim(value, limit: int):
    if value is None:
        return None
    text = json.dumps(value, default=str, ensure_ascii=False)
    return value if len(text) <= limit else text[:limit] + "…"


def _event(e: dict) -> dict:
    try:
        detail = json.loads(e.get("CloudTrailEvent") or "{}")
    except json.JSONDecodeError:
        detail = {}
    identity = detail.get("userIdentity") or {}
    return {
        "time": iso(e.get("EventTime")),
        "event_name": e.get("EventName"),
        "event_source": e.get("EventSource"),
        "username": e.get("Username"),
        "user_arn": identity.get("arn"),
        "resources": [
            {"type": r.get("ResourceType"), "name": r.get("ResourceName")}
            for r in e.get("Resources", [])
        ],
        "read_only": str(e.get("ReadOnly", "")).lower() == "true",
        "error_code": detail.get("errorCode"),
        "error_message": detail.get("errorMessage"),
        "source_ip": detail.get("sourceIPAddress"),
        "user_agent": (detail.get("userAgent") or "")[:120] or None,
        "request_parameters": _trim(detail.get("requestParameters"), REQUEST_PARAMS_CHARS),
    }


@tool(
    name="cloudtrail_lookup_events",
    group="cloudtrail",
    label="CloudTrail events",
    description="CloudTrail management events of the last 90 days: who changed what and "
    "when, e.g. ReplaceRouteTableAssociation on a subnet, StopInstances / StartInstances, "
    "AuthorizeSecurityGroupIngress, ChangeResourceRecordSets, ModifyTargetGroup. Filter by ONE "
    "of resource_name (a resource id such as subnet-..., sg-..., i-..., rtb-...), event_name, "
    "username or event_source. Read-only events (Describe*, List*, Get*) are skipped unless "
    "include_read_only is true. Newest first; times are UTC.",
    input_schema={
        "type": "object",
        "properties": {
            "resource_name": {"type": "string", "description": "e.g. subnet-0a1b..."},
            "event_name": {"type": "string", "description": "e.g. ReplaceRouteTableAssociation"},
            "username": {"type": "string"},
            "event_source": {"type": "string", "description": "e.g. ec2.amazonaws.com"},
            "start_time": ISO_TIME_SCHEMA,
            "end_time": ISO_TIME_SCHEMA,
            "hours": hours_schema(default=24, maximum=2160),
            "include_read_only": {"type": "boolean"},
            "max_items": {
                "type": "integer",
                "minimum": 1,
                "maximum": 25,
                "description": "Maximum number of events (default 15)",
            },
        },
    },
    aws_actions=["cloudtrail:LookupEvents"],
)
def cloudtrail_lookup_events(session: boto3.Session, params: dict) -> dict:
    filters = [(k, params[k]) for k in LOOKUP_KEYS if params.get(k)]
    if len(filters) > 1:
        return {
            "error": "INVALID_INPUT: CloudTrail filters by one attribute per call; pass only "
            "one of resource_name, event_name, username, event_source"
        }
    start, end, err = time_window(params, default_hours=24, max_hours=2160)
    if err:
        return {"error": err}
    limit = int(params.get("max_items") or 15)
    include_read_only = bool(params.get("include_read_only"))

    kwargs: dict = {"StartTime": start, "EndTime": end, "MaxResults": 50}
    if filters:
        key, value = filters[0]
        kwargs["LookupAttributes"] = [{"AttributeKey": LOOKUP_KEYS[key], "AttributeValue": value}]
    ct = session.client("cloudtrail")
    events: list[dict] = []
    scanned = 0
    token = None
    for _ in range(MAX_PAGES):
        resp = ct.lookup_events(**kwargs, **({"NextToken": token} if token else {}))
        for e in resp.get("Events", []):
            scanned += 1
            if not include_read_only and str(e.get("ReadOnly", "")).lower() == "true":
                continue
            events.append(_event(e))
            if len(events) >= limit:
                break
        token = resp.get("NextToken")
        if not token or len(events) >= limit:
            break
    return {
        "filter": {filters[0][0]: filters[0][1]} if filters else None,
        "window": window(start, end),
        "events": events,
        "events_scanned": scanned,
        "_truncated": bool(token),
    }
