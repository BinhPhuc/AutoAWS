"""Logs group: CloudWatch Logs Insights. STUB — planned for milestone M3.

TODO(M3): implement logs_insights_query:
  - params: log_group_names, query (Logs Insights syntax) or a preset ("errors"),
    start/end relative to the incident time, limit
  - StartQuery -> poll GetQueryResults (timeout ~20s) -> return rows (capped) and a
    summary; filter by error level before sending to the LLM.
"""

import boto3

from app.aws.registry import tool

NOT_IMPLEMENTED = {"error": "NOT_IMPLEMENTED: CloudWatch Logs tool is planned for M3"}


@tool(
    name="logs_insights_query",
    group="logs",
    label="CloudWatch Logs query",
    description="(Not implemented yet) Search application logs in CloudWatch Logs around the "
    "incident time for errors.",
    input_schema={
        "type": "object",
        "properties": {
            "log_group_names": {"type": "array", "items": {"type": "string"}},
            "query": {"type": "string"},
            "hours": {"type": "integer", "minimum": 1, "maximum": 24},
        },
        "required": ["log_group_names"],
    },
    aws_actions=["logs:StartQuery", "logs:GetQueryResults", "logs:DescribeLogGroups"],
    stub=True,
)
def logs_insights_query(session: boto3.Session, params: dict) -> dict:
    return dict(NOT_IMPLEMENTED)
