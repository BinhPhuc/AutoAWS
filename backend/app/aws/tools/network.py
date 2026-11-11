"""Network group: security groups, NACLs, route tables, subnets, gateways, Elastic IPs."""

import boto3

from app.aws.registry import tool
from app.aws.tools._common import MAX_ITEMS_SCHEMA, cap, str_list_schema, tag

# NACL entries carry IP protocol numbers
_PROTOCOLS = {"-1": "all", "1": "icmp", "6": "tcp", "17": "udp", "58": "icmpv6"}


def _vpc_filter(params: dict, filters: list[dict]) -> list[dict]:
    if params.get("vpc_id"):
        filters.append({"Name": "vpc-id", "Values": [params["vpc_id"]]})
    return filters


def _port_range(perm: dict) -> str:
    proto = perm.get("IpProtocol", "-1")
    if proto == "-1":
        return "all"
    frm, to = perm.get("FromPort"), perm.get("ToPort")
    if frm is None:
        return proto
    return f"{frm}/{proto}" if frm == to else f"{frm}-{to}/{proto}"


def _sources(perm: dict) -> list[str]:
    out = [r["CidrIp"] for r in perm.get("IpRanges", [])]
    out += [r["CidrIpv6"] for r in perm.get("Ipv6Ranges", [])]
    out += [g["GroupId"] for g in perm.get("UserIdGroupPairs", [])]
    out += [p["PrefixListId"] for p in perm.get("PrefixListIds", [])]
    return out


@tool(
    name="describe_security_groups",
    group="network",
    label="Security groups",
    description="Inbound and outbound rules of security groups. Filter by group ids or VPC.",
    input_schema={
        "type": "object",
        "properties": {
            "group_ids": str_list_schema("Security group ids, e.g. ['sg-0abc...']"),
            "vpc_id": {"type": "string"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["ec2:DescribeSecurityGroups"],
)
def describe_security_groups(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    kwargs: dict = {}
    if params.get("group_ids"):
        kwargs["GroupIds"] = params["group_ids"]
    filters = _vpc_filter(params, [])
    if filters:
        kwargs["Filters"] = filters
    groups = []
    for page in ec2.get_paginator("describe_security_groups").paginate(**kwargs):
        for g in page["SecurityGroups"]:
            groups.append(
                {
                    "group_id": g["GroupId"],
                    "name": g.get("GroupName"),
                    "vpc_id": g.get("VpcId"),
                    "inbound": [
                        {"ports": _port_range(p), "sources": _sources(p)}
                        for p in g.get("IpPermissions", [])
                    ],
                    "outbound": [
                        {"ports": _port_range(p), "destinations": _sources(p)}
                        for p in g.get("IpPermissionsEgress", [])
                    ],
                }
            )
    items, truncated = cap(groups, params)
    return {"security_groups": items, "_truncated": truncated}


@tool(
    name="describe_network_acls",
    group="network",
    label="Network ACLs",
    description="Network ACL entries (rule number, allow/deny, ports, CIDR) for subnets or a VPC. "
    "Rules are evaluated in ascending rule_number order.",
    input_schema={
        "type": "object",
        "properties": {
            "subnet_ids": str_list_schema("Subnet ids to find the ACLs of"),
            "vpc_id": {"type": "string"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["ec2:DescribeNetworkAcls"],
)
def describe_network_acls(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    filters = _vpc_filter(params, [])
    if params.get("subnet_ids"):
        filters.append({"Name": "association.subnet-id", "Values": params["subnet_ids"]})
    kwargs = {"Filters": filters} if filters else {}
    acls = []
    for page in ec2.get_paginator("describe_network_acls").paginate(**kwargs):
        for a in page["NetworkAcls"]:
            entries = sorted(a.get("Entries", []), key=lambda e: (e.get("Egress"), e["RuleNumber"]))
            acls.append(
                {
                    "acl_id": a["NetworkAclId"],
                    "vpc_id": a.get("VpcId"),
                    "is_default": a.get("IsDefault"),
                    "subnet_ids": [x["SubnetId"] for x in a.get("Associations", [])],
                    "entries": [
                        {
                            "rule_number": e["RuleNumber"],
                            "direction": "egress" if e.get("Egress") else "ingress",
                            "action": e.get("RuleAction"),
                            "protocol": _PROTOCOLS.get(str(e.get("Protocol")), e.get("Protocol")),
                            "ports": (
                                f"{e['PortRange']['From']}-{e['PortRange']['To']}"
                                if e.get("PortRange")
                                else "all"
                            ),
                            "cidr": e.get("CidrBlock") or e.get("Ipv6CidrBlock"),
                        }
                        for e in entries
                    ],
                }
            )
    items, truncated = cap(acls, params)
    return {"network_acls": items, "_truncated": truncated}


@tool(
    name="describe_route_tables",
    group="network",
    label="Route tables",
    description="Route tables with their routes and subnet associations. A subnet without an "
    "explicit association uses the VPC's main route table. Check for a 0.0.0.0/0 route to an "
    "igw-* (public) or nat-* (private) target.",
    input_schema={
        "type": "object",
        "properties": {
            "subnet_ids": str_list_schema("Subnet ids to find the route table of"),
            "vpc_id": {"type": "string"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["ec2:DescribeRouteTables", "ec2:DescribeSubnets"],
)
def describe_route_tables(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    subnet_ids = params.get("subnet_ids") or []
    filters = _vpc_filter(params, [])
    if subnet_ids:
        filters.append({"Name": "association.subnet-id", "Values": subnet_ids})
    kwargs = {"Filters": filters} if filters else {}
    tables = []
    for page in ec2.get_paginator("describe_route_tables").paginate(**kwargs):
        for rt in page["RouteTables"]:
            tables.append(_route_table(rt))

    # A subnet with no explicit association uses its VPC's main table. Add that table for
    # each such subnet (not only when none matched), so the agent sees the effective
    # routing of every subnet it asked about.
    covered = {sid for t in tables for sid in t["subnet_ids"]}
    implicit = [s for s in subnet_ids if s not in covered]
    if implicit:
        by_vpc: dict[str, list[str]] = {}
        for s in ec2.describe_subnets(SubnetIds=implicit)["Subnets"]:
            by_vpc.setdefault(s["VpcId"], []).append(s["SubnetId"])
        resp = ec2.describe_route_tables(
            Filters=[
                {"Name": "vpc-id", "Values": sorted(by_vpc)},
                {"Name": "association.main", "Values": ["true"]},
            ]
        )
        existing = {t["route_table_id"]: t for t in tables}
        for rt in resp["RouteTables"]:
            t = existing.get(rt["RouteTableId"]) or _route_table(rt)
            t["implicit_for_subnets"] = by_vpc.get(t["vpc_id"], [])
            if rt["RouteTableId"] not in existing:
                tables.append(t)
    items, truncated = cap(tables, params)
    return {"route_tables": items, "_truncated": truncated}


def _route_table(rt: dict) -> dict:
    return {
        "route_table_id": rt["RouteTableId"],
        "vpc_id": rt.get("VpcId"),
        "name": tag(rt.get("Tags")),
        "main": any(a.get("Main") for a in rt.get("Associations", [])),
        "subnet_ids": [a["SubnetId"] for a in rt.get("Associations", []) if a.get("SubnetId")],
        "routes": [
            {
                "destination": r.get("DestinationCidrBlock")
                or r.get("DestinationIpv6CidrBlock")
                or r.get("DestinationPrefixListId"),
                "target": r.get("GatewayId")
                or r.get("NatGatewayId")
                or r.get("InstanceId")
                or r.get("NetworkInterfaceId")
                or r.get("TransitGatewayId")
                or r.get("VpcPeeringConnectionId"),
                "state": r.get("State"),
            }
            for r in rt.get("Routes", [])
        ],
    }


@tool(
    name="describe_subnets",
    group="network",
    label="Subnets",
    description="Subnet CIDR, availability zone, VPC and whether instances get a public IP on "
    "launch.",
    input_schema={
        "type": "object",
        "properties": {
            "subnet_ids": str_list_schema("Subnet ids"),
            "vpc_id": {"type": "string"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["ec2:DescribeSubnets"],
)
def describe_subnets(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    kwargs: dict = {}
    if params.get("subnet_ids"):
        kwargs["SubnetIds"] = params["subnet_ids"]
    filters = _vpc_filter(params, [])
    if filters:
        kwargs["Filters"] = filters
    subnets = []
    for page in ec2.get_paginator("describe_subnets").paginate(**kwargs):
        for s in page["Subnets"]:
            subnets.append(
                {
                    "subnet_id": s["SubnetId"],
                    "name": tag(s.get("Tags")),
                    "vpc_id": s.get("VpcId"),
                    "cidr": s.get("CidrBlock"),
                    "availability_zone": s.get("AvailabilityZone"),
                    "map_public_ip_on_launch": s.get("MapPublicIpOnLaunch"),
                    "available_ip_count": s.get("AvailableIpAddressCount"),
                }
            )
    items, truncated = cap(subnets, params)
    return {"subnets": items, "_truncated": truncated}


@tool(
    name="describe_internet_gateways",
    group="network",
    label="Internet gateways",
    description="Internet gateways and which VPCs they are attached to.",
    input_schema={
        "type": "object",
        "properties": {"vpc_id": {"type": "string"}, "max_items": MAX_ITEMS_SCHEMA},
    },
    aws_actions=["ec2:DescribeInternetGateways"],
)
def describe_internet_gateways(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    kwargs: dict = {}
    if params.get("vpc_id"):
        kwargs["Filters"] = [{"Name": "attachment.vpc-id", "Values": [params["vpc_id"]]}]
    igws = []
    for page in ec2.get_paginator("describe_internet_gateways").paginate(**kwargs):
        for g in page["InternetGateways"]:
            igws.append(
                {
                    "igw_id": g["InternetGatewayId"],
                    "attached_vpcs": [
                        {"vpc_id": a.get("VpcId"), "state": a.get("State")}
                        for a in g.get("Attachments", [])
                    ],
                }
            )
    items, truncated = cap(igws, params)
    return {"internet_gateways": items, "_truncated": truncated}


@tool(
    name="describe_nat_gateways",
    group="network",
    label="NAT gateways",
    description="NAT gateways (state, subnet, public/private IPs, failure reason). A private "
    "subnet reaches the Internet only through a 0.0.0.0/0 route to an available nat-*.",
    input_schema={
        "type": "object",
        "properties": {
            "nat_gateway_ids": str_list_schema("NAT gateway ids, e.g. ['nat-0abc...']"),
            "vpc_id": {"type": "string"},
            "subnet_ids": str_list_schema("Subnets the NAT gateways live in"),
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["ec2:DescribeNatGateways"],
)
def describe_nat_gateways(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    kwargs: dict = {}
    if params.get("nat_gateway_ids"):
        kwargs["NatGatewayIds"] = params["nat_gateway_ids"]
    filters = _vpc_filter(params, [])
    if params.get("subnet_ids"):
        filters.append({"Name": "subnet-id", "Values": params["subnet_ids"]})
    if filters:
        kwargs["Filter"] = filters  # this API names it Filter, not Filters
    nats = []
    for page in ec2.get_paginator("describe_nat_gateways").paginate(**kwargs):
        for n in page["NatGateways"]:
            addresses = n.get("NatGatewayAddresses", [])
            nats.append(
                {
                    "nat_gateway_id": n["NatGatewayId"],
                    "name": tag(n.get("Tags")),
                    "state": n.get("State"),
                    "connectivity_type": n.get("ConnectivityType"),
                    "vpc_id": n.get("VpcId"),
                    "subnet_id": n.get("SubnetId"),
                    "public_ips": [a["PublicIp"] for a in addresses if a.get("PublicIp")],
                    "private_ips": [a["PrivateIp"] for a in addresses if a.get("PrivateIp")],
                    "failure_code": n.get("FailureCode"),
                    "failure_message": n.get("FailureMessage"),
                }
            )
    items, truncated = cap(nats, params)
    return {"nat_gateways": items, "_truncated": truncated}


@tool(
    name="describe_addresses",
    group="network",
    label="Elastic IPs",
    description="Elastic IP addresses of the account and what they are attached to. An "
    "instance without an Elastic IP gets a NEW public IP after stop/start, so DNS records "
    "pointing at the old IP break.",
    input_schema={
        "type": "object",
        "properties": {
            "instance_ids": str_list_schema("Only Elastic IPs attached to these instances"),
            "public_ips": str_list_schema("Look up these public IPs"),
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["ec2:DescribeAddresses"],
)
def describe_addresses(session: boto3.Session, params: dict) -> dict:
    ec2 = session.client("ec2")
    kwargs: dict = {}
    if params.get("public_ips"):
        kwargs["PublicIps"] = params["public_ips"]
    if params.get("instance_ids"):
        kwargs["Filters"] = [{"Name": "instance-id", "Values": params["instance_ids"]}]
    addresses = [
        {
            "public_ip": a.get("PublicIp"),
            "allocation_id": a.get("AllocationId"),
            "name": tag(a.get("Tags")),
            "instance_id": a.get("InstanceId"),
            "network_interface_id": a.get("NetworkInterfaceId"),
            "private_ip": a.get("PrivateIpAddress"),
            "association_id": a.get("AssociationId"),
            "domain": a.get("Domain"),
        }
        for a in ec2.describe_addresses(**kwargs)["Addresses"]
    ]
    items, truncated = cap(addresses, params)
    return {"elastic_ips": items, "_truncated": truncated}
