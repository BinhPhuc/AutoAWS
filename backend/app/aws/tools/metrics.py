"""Metrics group: CloudWatch metric series and alarms.

The series is summarised (min / max / latest and the points where the value changed) so
the LLM sees *when* something started without a raw dump of hundreds of datapoints.
"""

import math

import boto3

from app.aws.registry import tool
from app.aws.tools._common import (
    ISO_TIME_SCHEMA,
    MAX_ITEMS_SCHEMA,
    cap,
    hours_schema,
    iso,
    time_window,
    window,
)

STATS = ["Average", "Sum", "Minimum", "Maximum", "SampleCount", "p50", "p90", "p95", "p99"]
MAX_POINTS = 1440  # per query; the period grows to stay under it
SHOWN_POINTS = 24  # the sanitizer keeps at most 25 list items


def _num(value: float) -> float | int:
    rounded = round(value, 4)
    return int(rounded) if rounded == int(rounded) else rounded


@tool(
    name="cloudwatch_get_metric_data",
    group="metrics",
    label="CloudWatch metrics",
    description="Time series of one CloudWatch metric over a window, summarised: min, max, "
    "latest value and the points where the value changed (to see when an incident started). "
    "Examples: AWS/ApplicationELB UnHealthyHostCount with dimensions TargetGroup + "
    "LoadBalancer (the ARN suffixes 'targetgroup/...' and 'app/...'); AWS/EC2 CPUUtilization "
    "or StatusCheckFailed with InstanceId. When nothing matches, the result lists the "
    "dimension sets that exist for the metric.",
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string", "description": "e.g. AWS/EC2, AWS/ApplicationELB"},
            "metric_name": {"type": "string"},
            "dimensions": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": '{name: value}, e.g. {"InstanceId": "i-0abc..."}',
            },
            "stat": {
                "type": "string",
                "enum": STATS,
                "description": "Default Average; use Sum for counts",
            },
            "period_seconds": {"type": "integer", "minimum": 60, "maximum": 86400},
            "start_time": ISO_TIME_SCHEMA,
            "end_time": ISO_TIME_SCHEMA,
            "hours": hours_schema(default=3, maximum=336),
        },
        "required": ["namespace", "metric_name"],
    },
    aws_actions=["cloudwatch:GetMetricData", "cloudwatch:ListMetrics"],
)
def cloudwatch_get_metric_data(session: boto3.Session, params: dict) -> dict:
    start, end, err = time_window(params, default_hours=3, max_hours=336)
    if err:
        return {"error": err}
    span = (end - start).total_seconds()
    period = max(60, int(params.get("period_seconds") or 300) // 60 * 60)
    if span / period > MAX_POINTS:
        period = math.ceil(span / MAX_POINTS / 60) * 60
    dims = params.get("dimensions") or {}
    stat = params.get("stat") or "Average"
    metric = {
        "Namespace": params["namespace"],
        "MetricName": params["metric_name"],
        "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()],
    }
    cw = session.client("cloudwatch")
    points: list[tuple] = []
    status = None
    for page in cw.get_paginator("get_metric_data").paginate(
        MetricDataQueries=[
            {
                "Id": "m1",
                "MetricStat": {"Metric": metric, "Period": period, "Stat": stat},
                "ReturnData": True,
            }
        ],
        StartTime=start,
        EndTime=end,
        ScanBy="TimestampAscending",
    ):
        for result in page["MetricDataResults"]:
            points += zip(result.get("Timestamps", []), result.get("Values", []), strict=False)
            status = result.get("StatusCode") or status
    points.sort(key=lambda p: p[0])

    out: dict = {
        "namespace": params["namespace"],
        "metric_name": params["metric_name"],
        "dimensions": dims,
        "stat": stat,
        "period_seconds": period,
        "window": window(start, end),
        "datapoints": len(points),
        "status": status,
    }
    if not points:
        out["available_dimensions"] = _dimension_sets(
            cw, params["namespace"], params["metric_name"]
        )
        return out
    values = [v for _, v in points]
    out["min"] = _num(min(values))
    out["max"] = _num(max(values))
    out["latest"] = {"time": iso(points[-1][0]), "value": _num(points[-1][1])}
    if len(points) <= SHOWN_POINTS:
        out["points"] = [[iso(t), _num(v)] for t, v in points]
    else:
        changes = [p for i, p in enumerate(points) if i == 0 or p[1] != points[i - 1][1]]
        out["changes"] = [[iso(t), _num(v)] for t, v in changes[-SHOWN_POINTS:]]
        out["changes_total"] = len(changes)
    return out


def _dimension_sets(cw, namespace: str, metric_name: str) -> list[dict]:
    sets = []
    for page in cw.get_paginator("list_metrics").paginate(
        Namespace=namespace, MetricName=metric_name
    ):
        for m in page["Metrics"]:
            sets.append({d["Name"]: d["Value"] for d in m.get("Dimensions", [])})
            if len(sets) >= 10:
                return sets
    return sets


@tool(
    name="cloudwatch_describe_alarms",
    group="metrics",
    label="CloudWatch alarms",
    description="CloudWatch metric alarms: state (ALARM / OK / INSUFFICIENT_DATA), state "
    "reason and when it last changed, plus the metric, dimensions and threshold they watch. "
    "Alarms in ALARM come first.",
    input_schema={
        "type": "object",
        "properties": {
            "state": {"type": "string", "enum": ["ALARM", "OK", "INSUFFICIENT_DATA"]},
            "alarm_name_prefix": {"type": "string"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["cloudwatch:DescribeAlarms"],
)
def cloudwatch_describe_alarms(session: boto3.Session, params: dict) -> dict:
    cw = session.client("cloudwatch")
    kwargs: dict = {"AlarmTypes": ["MetricAlarm"]}
    if params.get("state"):
        kwargs["StateValue"] = params["state"]
    if params.get("alarm_name_prefix"):
        kwargs["AlarmNamePrefix"] = params["alarm_name_prefix"]
    alarms = []
    for page in cw.get_paginator("describe_alarms").paginate(**kwargs):
        for a in page.get("MetricAlarms", []):
            alarms.append(
                {
                    "name": a["AlarmName"],
                    "state": a.get("StateValue"),
                    "state_reason": a.get("StateReason"),
                    "state_updated": a.get("StateUpdatedTimestamp"),
                    "namespace": a.get("Namespace"),
                    "metric_name": a.get("MetricName"),
                    "dimensions": {d["Name"]: d["Value"] for d in a.get("Dimensions", [])},
                    "statistic": a.get("Statistic") or a.get("ExtendedStatistic"),
                    "comparison": a.get("ComparisonOperator"),
                    "threshold": a.get("Threshold"),
                    "period_seconds": a.get("Period"),
                    "evaluation_periods": a.get("EvaluationPeriods"),
                }
            )
    alarms.sort(
        key=lambda a: (
            a["state"] != "ALARM",
            -(a["state_updated"].timestamp() if a["state_updated"] else 0),
        )
    )
    for a in alarms:
        a["state_updated"] = iso(a["state_updated"])
    items, truncated = cap(alarms, params)
    return {"alarms": items, "_truncated": truncated}
