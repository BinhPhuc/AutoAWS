"""Load balancer group: ELBv2 (ALB/NLB) load balancers, listeners, target health."""

import boto3

from app.aws.registry import tool
from app.aws.tools._common import MAX_ITEMS_SCHEMA, cap, str_list_schema


@tool(
    name="elbv2_describe_load_balancers",
    group="elb",
    label="Load balancers",
    description="Application/Network load balancers with DNS name, scheme, state, security "
    "groups, subnets and listeners (port, protocol, forward target groups).",
    input_schema={
        "type": "object",
        "properties": {
            "names": str_list_schema("Load balancer names (optional)"),
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=[
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeListeners",
    ],
)
def elbv2_describe_load_balancers(session: boto3.Session, params: dict) -> dict:
    elb = session.client("elbv2")
    kwargs: dict = {}
    if params.get("names"):
        kwargs["Names"] = params["names"]
    lbs = []
    for page in elb.get_paginator("describe_load_balancers").paginate(**kwargs):
        for lb in page["LoadBalancers"]:
            listeners = []
            for lpage in elb.get_paginator("describe_listeners").paginate(
                LoadBalancerArn=lb["LoadBalancerArn"]
            ):
                for ls in lpage["Listeners"]:
                    listeners.append(
                        {
                            "port": ls.get("Port"),
                            "protocol": ls.get("Protocol"),
                            "default_actions": [
                                {
                                    "type": a.get("Type"),
                                    "target_group_arn": a.get("TargetGroupArn"),
                                    "redirect": a.get("RedirectConfig"),
                                }
                                for a in ls.get("DefaultActions", [])
                            ],
                        }
                    )
            lbs.append(
                {
                    "arn": lb["LoadBalancerArn"],
                    "name": lb["LoadBalancerName"],
                    "dns_name": lb.get("DNSName"),
                    "scheme": lb.get("Scheme"),
                    "type": lb.get("Type"),
                    "state": lb.get("State", {}).get("Code"),
                    "vpc_id": lb.get("VpcId"),
                    "security_groups": lb.get("SecurityGroups", []),
                    "subnets": [az.get("SubnetId") for az in lb.get("AvailabilityZones", [])],
                    "listeners": listeners,
                }
            )
    items, truncated = cap(lbs, params)
    return {"load_balancers": items, "_truncated": truncated}


@tool(
    name="elbv2_describe_target_health",
    group="elb",
    label="Target health",
    description="Target groups with their health check configuration (path, port, matcher) and "
    "the health state and reason of every target. Filter by target group ARN or load balancer "
    "ARN.",
    input_schema={
        "type": "object",
        "properties": {
            "target_group_arn": {"type": "string"},
            "load_balancer_arn": {"type": "string"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=[
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
    ],
)
def elbv2_describe_target_health(session: boto3.Session, params: dict) -> dict:
    elb = session.client("elbv2")
    kwargs: dict = {}
    if params.get("target_group_arn"):
        kwargs["TargetGroupArns"] = [params["target_group_arn"]]
    elif params.get("load_balancer_arn"):
        kwargs["LoadBalancerArn"] = params["load_balancer_arn"]
    groups = []
    for page in elb.get_paginator("describe_target_groups").paginate(**kwargs):
        for tg in page["TargetGroups"]:
            health = elb.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
            targets = [
                {
                    "id": t["Target"].get("Id"),
                    "port": t["Target"].get("Port"),
                    "state": t.get("TargetHealth", {}).get("State"),
                    "reason": t.get("TargetHealth", {}).get("Reason"),
                    "description": t.get("TargetHealth", {}).get("Description"),
                }
                for t in health.get("TargetHealthDescriptions", [])
            ]
            groups.append(
                {
                    "arn": tg["TargetGroupArn"],
                    "name": tg.get("TargetGroupName"),
                    "protocol": tg.get("Protocol"),
                    "port": tg.get("Port"),
                    "target_type": tg.get("TargetType"),
                    "health_check": {
                        "protocol": tg.get("HealthCheckProtocol"),
                        "port": tg.get("HealthCheckPort"),
                        "path": tg.get("HealthCheckPath"),
                        "interval_seconds": tg.get("HealthCheckIntervalSeconds"),
                        "timeout_seconds": tg.get("HealthCheckTimeoutSeconds"),
                        "healthy_threshold": tg.get("HealthyThresholdCount"),
                        "unhealthy_threshold": tg.get("UnhealthyThresholdCount"),
                        "matcher": (tg.get("Matcher") or {}).get("HttpCode"),
                    },
                    "healthy_count": sum(1 for t in targets if t["state"] == "healthy"),
                    "targets": targets,
                }
            )
    items, truncated = cap(groups, params)
    return {"target_groups": items, "_truncated": truncated}
