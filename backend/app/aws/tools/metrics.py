"""Metrics group: CloudWatch GetMetricData. STUB — planned for milestone M3.

TODO(M3): implement cloudwatch_get_metric_data:
  - params: namespace, metric_name, dimensions {name: value}, start/end (ISO or relative
    like "-2h"), period, stat (Sum/Average/p99)
  - cap the time window (<= 24h) and number of datapoints; return datapoints + a short
    summary (min/max/first spike) so the LLM does not need the raw series.
"""

import boto3

from app.aws.registry import tool

NOT_IMPLEMENTED = {"error": "NOT_IMPLEMENTED: CloudWatch metrics tool is planned for M3"}


@tool(
    name="cloudwatch_get_metric_data",
    group="metrics",
    label="CloudWatch metrics",
    description="(Not implemented yet) Time series for a CloudWatch metric, e.g. ALB "
    "HTTPCode_ELB_5XX_Count, to find when an incident started.",
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "metric_name": {"type": "string"},
            "dimensions": {"type": "object", "additionalProperties": {"type": "string"}},
            "hours": {"type": "integer", "minimum": 1, "maximum": 24},
        },
        "required": ["namespace", "metric_name"],
    },
    aws_actions=["cloudwatch:GetMetricData", "cloudwatch:ListMetrics"],
    stub=True,
)
def cloudwatch_get_metric_data(session: boto3.Session, params: dict) -> dict:
    return dict(NOT_IMPLEMENTED)
