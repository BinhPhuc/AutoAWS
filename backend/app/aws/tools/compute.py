"""Compute group: EC2 instances, status checks, SSM agent."""

import boto3

from app.aws.registry import tool
from app.aws.tools._common import MAX_ITEMS_SCHEMA, cap, str_list_schema, tag


@tool(
    name="get_caller_identity",
    group="compute",
    label="Caller identity",
    description="Return the AWS account id and ARN the connection is using. "
    "Useful as a first sanity check.",
    input_schema={"type": "object", "properties": {}},
    aws_actions=["sts:GetCallerIdentity"],
)
def get_caller_identity(session: boto3.Session, params: dict) -> dict:
    ident = session.client("sts").get_caller_identity()
    return {"account_id": ident["Account"], "arn": ident["Arn"], "user_id": ident["UserId"]}


@tool(
    name="describe_instances",
    group="compute",
    label="EC2 instances",
    description="List EC2 instances with state, public/private IPs, subnet, VPC and security "
    "groups. Filter by instance ids or by Name tag (substring).",
    input_schema={
        "type": "object",
        "properties": {
            "instance_ids": str_list_schema("Instance ids, e.g. ['i-0abc...']"),
            "name_tag": {"type": "string", "description": "Substring of the Name tag"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["ec2:DescribeInstances"],
)
def describe_instances(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    kwargs: dict = {}
    if params.get("instance_ids"):
        kwargs["InstanceIds"] = params["instance_ids"]
    if params.get("name_tag"):
        kwargs["Filters"] = [{"Name": "tag:Name", "Values": [f"*{params['name_tag']}*"]}]
    instances = []
    for page in ec2.get_paginator("describe_instances").paginate(**kwargs):
        for res in page["Reservations"]:
            for i in res["Instances"]:
                instances.append(
                    {
                        "instance_id": i["InstanceId"],
                        "name": tag(i.get("Tags")),
                        "state": i["State"]["Name"],
                        "instance_type": i.get("InstanceType"),
                        "public_ip": i.get("PublicIpAddress"),
                        "private_ip": i.get("PrivateIpAddress"),
                        "subnet_id": i.get("SubnetId"),
                        "vpc_id": i.get("VpcId"),
                        "availability_zone": i.get("Placement", {}).get("AvailabilityZone"),
                        "security_group_ids": [g["GroupId"] for g in i.get("SecurityGroups", [])],
                        "iam_instance_profile": (i.get("IamInstanceProfile") or {}).get("Arn"),
                        "launch_time": i.get("LaunchTime"),
                        "state_transition_reason": i.get("StateTransitionReason") or None,
                    }
                )
    items, truncated = cap(instances, params)
    return {"instances": items, "_truncated": truncated}


@tool(
    name="describe_instance_status",
    group="compute",
    label="Instance status checks",
    description="System and instance status checks (the '2/2 checks') and scheduled events "
    "for EC2 instances.",
    input_schema={
        "type": "object",
        "properties": {"instance_ids": str_list_schema("Instance ids (optional)")},
    },
    aws_actions=["ec2:DescribeInstanceStatus"],
)
def describe_instance_status(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    kwargs: dict = {"IncludeAllInstances": True}
    if params.get("instance_ids"):
        kwargs["InstanceIds"] = params["instance_ids"]
    statuses = []
    for page in ec2.get_paginator("describe_instance_status").paginate(**kwargs):
        for s in page["InstanceStatuses"]:
            statuses.append(
                {
                    "instance_id": s["InstanceId"],
                    "instance_state": s["InstanceState"]["Name"],
                    "system_status": s.get("SystemStatus", {}).get("Status"),
                    "instance_status": s.get("InstanceStatus", {}).get("Status"),
                    "events": [
                        {"code": e.get("Code"), "description": e.get("Description")}
                        for e in s.get("Events", [])
                    ],
                }
            )
    items, truncated = cap(statuses, params)
    return {"statuses": items, "_truncated": truncated}


@tool(
    name="ssm_describe_instance_information",
    group="compute",
    label="SSM Agent status",
    description="Whether SSM Agent is online on instances (enables Session Manager access "
    "without SSH).",
    input_schema={
        "type": "object",
        "properties": {"instance_ids": str_list_schema("Instance ids (optional)")},
    },
    aws_actions=["ssm:DescribeInstanceInformation"],
)
def ssm_describe_instance_information(session: boto3.Session, params: dict) -> dict:
    ssm = session.client("ssm")
    kwargs: dict = {}
    if params.get("instance_ids"):
        kwargs["Filters"] = [{"Key": "InstanceIds", "Values": params["instance_ids"]}]
    infos = []
    for page in ssm.get_paginator("describe_instance_information").paginate(**kwargs):
        for i in page["InstanceInformationList"]:
            infos.append(
                {
                    "instance_id": i["InstanceId"],
                    "ping_status": i.get("PingStatus"),
                    "agent_version": i.get("AgentVersion"),
                    "platform": (
                        f"{i.get('PlatformName', '')} {i.get('PlatformVersion', '')}".strip()
                    ),
                    "last_ping": i.get("LastPingDateTime"),
                }
            )
    items, truncated = cap(infos, params)
    return {"managed_instances": items, "_truncated": truncated}
