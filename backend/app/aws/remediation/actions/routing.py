"""Routes and route table associations."""

from app.aws.remediation.base import (
    ActionSpec,
    Session,
    cidr_problem,
    expect_dry_run,
    network,
    preview,
    register,
)

# target_type -> (key of CreateRoute / route entries, id prefix)
TARGETS = {
    "internet_gateway": ("GatewayId", "igw-"),
    "nat_gateway": ("NatGatewayId", "nat-"),
    "transit_gateway": ("TransitGatewayId", "tgw-"),
    "vpc_peering_connection": ("VpcPeeringConnectionId", "pcx-"),
    "network_interface": ("NetworkInterfaceId", "eni-"),
}

_EXTRA_READS = (
    "ec2:DescribeNetworkInterfaces",
    "ec2:DescribeTransitGateways",
    "ec2:DescribeVpcPeeringConnections",
)


def _route_target(route: dict) -> tuple[str, str]:
    """(target_type, target_id) of a route entry; ('local', 'local') for the VPC route."""
    if route.get("GatewayId") == "local":
        return "local", "local"
    for target_type, (key, _) in TARGETS.items():
        if route.get(key):
            return target_type, route[key]
    for key in ("GatewayId", "EgressOnlyInternetGatewayId", "InstanceId", "CarrierGatewayId"):
        if route.get(key):
            return key, route[key]
    return "unknown", "?"


def _destination(route: dict) -> str | None:
    dest = route.get("DestinationCidrBlock") or route.get("DestinationIpv6CidrBlock")
    return str(network(dest)) if dest else None


def routes(rt: dict) -> list[str]:
    out = []
    for r in rt.get("Routes", []):
        dest = _destination(r) or r.get("DestinationPrefixListId") or "?"
        out.append(f"{dest} -> {_route_target(r)[1]} ({r.get('State', 'active')})")
    return sorted(out)


def has_igw_default(rt: dict) -> bool:
    return any(
        r.get("DestinationCidrBlock") == "0.0.0.0/0"
        and (r.get("GatewayId") or "").startswith("igw-")
        and r.get("State", "active") == "active"
        for r in rt.get("Routes", [])
    )


def _table(ec2, route_table_id: str) -> dict:
    return ec2.describe_route_tables(RouteTableIds=[route_table_id])["RouteTables"][0]


def _find(rt: dict, destination: str) -> dict | None:
    dest = str(network(destination))
    return next((r for r in rt.get("Routes", []) if _destination(r) == dest), None)


def _target_facts(ec2, target_type: str, target_id: str) -> dict:
    """What the pre-check needs to know about a route target (read-only)."""
    if target_type == "internet_gateway":
        igw = ec2.describe_internet_gateways(InternetGatewayIds=[target_id])["InternetGateways"][0]
        vpcs = [
            a["VpcId"]
            for a in igw.get("Attachments", [])
            if a.get("State") in ("available", "attached")
        ]
        return {"vpc_ids": sorted(vpcs), "state": "available" if vpcs else "detached"}
    if target_type == "nat_gateway":
        nat = ec2.describe_nat_gateways(NatGatewayIds=[target_id])["NatGateways"][0]
        return {"vpc_ids": [nat.get("VpcId")], "state": nat.get("State")}
    if target_type == "transit_gateway":
        tgw = ec2.describe_transit_gateways(TransitGatewayIds=[target_id])["TransitGateways"][0]
        return {"vpc_ids": [], "state": tgw.get("State")}
    if target_type == "vpc_peering_connection":
        pcx = ec2.describe_vpc_peering_connections(VpcPeeringConnectionIds=[target_id])[
            "VpcPeeringConnections"
        ][0]
        vpcs = [
            pcx.get("RequesterVpcInfo", {}).get("VpcId"),
            pcx.get("AccepterVpcInfo", {}).get("VpcId"),
        ]
        return {"vpc_ids": sorted(v for v in vpcs if v), "state": pcx.get("Status", {}).get("Code")}
    eni = ec2.describe_network_interfaces(NetworkInterfaceIds=[target_id])["NetworkInterfaces"][0]
    return {"vpc_ids": [eni.get("VpcId")], "state": eni.get("Status")}


_READY = {"available", "active", "in-use", "attached"}


def _route_snapshot(read: Session, p: dict) -> dict:
    ec2 = read.client("ec2")
    rt = _table(ec2, p["route_table_id"])
    route = _find(rt, p["destination_cidr"]) if not cidr_problem(p["destination_cidr"]) else None
    snap = {
        "route_table_id": rt["RouteTableId"],
        "vpc_id": rt["VpcId"],
        "destination": p["destination_cidr"],
        "route": None
        if route is None
        else {
            "target_type": _route_target(route)[0],
            "target_id": _route_target(route)[1],
            "state": route.get("State", "active"),
        },
        "_routes": routes(rt),
    }
    if p.get("target_type") and p.get("target_id"):
        snap["target"] = _target_facts(ec2, p["target_type"], p["target_id"])
    return snap


def _target_problem(p: dict, s: dict) -> str | None:
    key, prefix = TARGETS[p["target_type"]]
    if not p["target_id"].startswith(prefix):
        return f"{p['target_id']} is not a {p['target_type']} id ({prefix}...)"
    facts = s["target"]
    if facts["vpc_ids"] and s["vpc_id"] not in facts["vpc_ids"]:
        return f"{p['target_id']} is not attached to {s['vpc_id']}"
    if facts["state"] not in _READY:
        return f"{p['target_id']} is {facts['state']}, not available"
    return None


def _add_precheck(p: dict, s: dict) -> str | None:
    if problem := cidr_problem(p["destination_cidr"]):
        return problem
    if s["route"]:
        r = s["route"]
        return (
            f"{p['route_table_id']} already routes {p['destination_cidr']} to {r['target_id']}; "
            "use route_replace"
        )
    return _target_problem(p, s)


def _replace_precheck(p: dict, s: dict) -> str | None:
    if problem := cidr_problem(p["destination_cidr"]):
        return problem
    r = s["route"]
    if r is None:
        return f"{p['route_table_id']} has no route for {p['destination_cidr']}; use route_add"
    if r["target_type"] == "local":
        return "The VPC local route cannot be changed"
    if r["target_type"] not in TARGETS:
        return f"Routes to {r['target_type']} targets are not supported"
    if (r["target_type"], r["target_id"]) == (p["target_type"], p["target_id"]):
        return f"{p['destination_cidr']} already goes to {p['target_id']}"
    return _target_problem(p, s)


def _delete_precheck(p: dict, s: dict) -> str | None:
    if problem := cidr_problem(p["destination_cidr"]):
        return problem
    r = s["route"]
    if r is None:
        return f"{p['route_table_id']} has no route for {p['destination_cidr']}"
    if r["target_type"] == "local":
        return "The VPC local route cannot be deleted"
    if r["target_type"] not in TARGETS:
        return f"Routes to {r['target_type']} targets are not supported"
    return None


def _route_kwargs(route_table_id: str, destination: str, target_type: str | None, target_id):
    net = network(destination)
    kwargs = {
        "RouteTableId": route_table_id,
        ("DestinationCidrBlock" if net.version == 4 else "DestinationIpv6CidrBlock"): str(net),
    }
    if target_type:
        kwargs[TARGETS[target_type][0]] = target_id
    return kwargs


def _write(read: Session, write: Session, p: dict, s: dict, verb: str, kwargs: dict) -> dict:
    getattr(write.client("ec2"), verb)(**kwargs)
    return {}


def _new(p: dict) -> dict:
    return _route_kwargs(
        p["route_table_id"], p["destination_cidr"], p["target_type"], p["target_id"]
    )


def _old(p: dict, s: dict) -> dict:
    r = s["route"]
    return _route_kwargs(
        p["route_table_id"], p["destination_cidr"], r["target_type"], r["target_id"]
    )


def _gone(p: dict) -> dict:
    return _route_kwargs(p["route_table_id"], p["destination_cidr"], None, None)


def _route_verify(expect_target: bool):
    def verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
        rt = _table(read.client("ec2"), p["route_table_id"])
        route = _find(rt, p["destination_cidr"])
        if expect_target:
            ok = (
                route is not None
                and _route_target(route) == (p["target_type"], p["target_id"])
                and route.get("State", "active") == "active"
            )
        else:
            ok = route is None
        return ok, f"{p['route_table_id']}: {', '.join(routes(rt))}"

    return verify


def _change(s: dict, after: str) -> list[dict]:
    return [
        {
            "field": f"Routes of {s['route_table_id']}",
            "before": ", ".join(s["_routes"]),
            "after": after,
        }
    ]


def _add_preview(p: dict, s: dict) -> dict:
    new = f"{p['destination_cidr']} -> {p['target_id']} (active)"
    public = (
        p["target_type"] == "internet_gateway" and network(p["destination_cidr"]).prefixlen == 0
    )
    return preview(
        f"Add route {p['destination_cidr']} -> {p['target_id']} to {p['route_table_id']}",
        _change(s, ", ".join(sorted([*s["_routes"], new]))),
        f"Every subnet using {p['route_table_id']} sends traffic for {p['destination_cidr']} "
        f"to {p['target_id']}" + (" (the subnets become public)." if public else "."),
        "medium" if public else "low",
        f"Delete the route {p['destination_cidr']} from {p['route_table_id']}",
        f"{p['route_table_id']} has an active route {p['destination_cidr']} -> {p['target_id']}.",
    )


def _replace_preview(p: dict, s: dict) -> dict:
    old = s["route"]["target_id"]
    after = [x for x in s["_routes"] if not x.startswith(f"{network(p['destination_cidr'])} ")]
    return preview(
        f"Route {p['destination_cidr']} to {p['target_id']} instead of {old} in "
        f"{p['route_table_id']}",
        _change(
            s, ", ".join(sorted([*after, f"{p['destination_cidr']} -> {p['target_id']} (active)"]))
        ),
        f"Every subnet using {p['route_table_id']} sends traffic for {p['destination_cidr']} "
        f"to {p['target_id']}.",
        "medium",
        f"Route {p['destination_cidr']} back to {old}",
        f"{p['route_table_id']} has an active route {p['destination_cidr']} -> {p['target_id']}.",
    )


def _delete_preview(p: dict, s: dict) -> dict:
    after = [x for x in s["_routes"] if not x.startswith(f"{network(p['destination_cidr'])} ")]
    return preview(
        f"Delete route {p['destination_cidr']} -> {s['route']['target_id']} from "
        f"{p['route_table_id']}",
        _change(s, ", ".join(after) or "none"),
        f"Traffic for {p['destination_cidr']} from subnets using {p['route_table_id']} follows "
        "the next most specific route, or is dropped.",
        "medium",
        f"Create the route {p['destination_cidr']} -> {s['route']['target_id']} again",
        f"{p['route_table_id']} has no route for {p['destination_cidr']}.",
    )


_ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "route_table_id": {"type": "string", "pattern": "^rtb-[0-9a-f]+$"},
        "destination_cidr": {"type": "string", "description": "e.g. 0.0.0.0/0 or 10.1.0.0/16"},
        "target_type": {"type": "string", "enum": sorted(TARGETS)},
        "target_id": {"type": "string", "pattern": "^(igw|nat|tgw|pcx|eni)-[0-9a-f]+$"},
    },
    "required": ["route_table_id", "destination_cidr", "target_type", "target_id"],
    "additionalProperties": False,
}

register(
    ActionSpec(
        name="route_add",
        group="Route table",
        label="Add route",
        description="Add a route to a route table: destination_cidr -> an Internet gateway, "
        "NAT gateway, transit gateway, VPC peering connection or network interface of the "
        "same VPC, e.g. 0.0.0.0/0 -> igw-... for a public subnet or -> nat-... for a private "
        "one. Only when the table has no route for that destination (else route_replace).",
        input_schema=_ROUTE_SCHEMA,
        write_actions=["ec2:CreateRoute", "ec2:DeleteRoute"],
        snapshot=_route_snapshot,
        precheck=_add_precheck,
        preview=_add_preview,
        execute=lambda read, write, p, s: _write(read, write, p, s, "create_route", _new(p)),
        verify=_route_verify(True),
        undo=lambda read, write, p, s, r: write.client("ec2").delete_route(**_gone(p)),
        undo_description=lambda p, s: f"Delete the route {p['destination_cidr']}",
        dry_run=lambda read, write, p, s: expect_dry_run(
            write.client("ec2").create_route, **_new(p)
        ),
    ),
    extra_reads=_EXTRA_READS,
)

register(
    ActionSpec(
        name="route_replace",
        group="Route table",
        label="Change route target",
        description="Point an EXISTING route of a route table to another target (same target "
        "types as route_add), e.g. a route to a deleted NAT gateway (blackhole) to the new one. "
        "The VPC local route cannot be changed.",
        input_schema=_ROUTE_SCHEMA,
        write_actions=["ec2:ReplaceRoute"],
        snapshot=_route_snapshot,
        precheck=_replace_precheck,
        preview=_replace_preview,
        execute=lambda read, write, p, s: _write(read, write, p, s, "replace_route", _new(p)),
        verify=_route_verify(True),
        undo=lambda read, write, p, s, r: write.client("ec2").replace_route(**_old(p, s)),
        undo_description=lambda p, s: (
            f"Route {p['destination_cidr']} back to {s['route']['target_id']}"
        ),
        dry_run=lambda read, write, p, s: expect_dry_run(
            write.client("ec2").replace_route, **_new(p)
        ),
    ),
    extra_reads=_EXTRA_READS,
)

register(
    ActionSpec(
        name="route_delete",
        group="Route table",
        label="Delete route",
        description="Delete ONE route (not the VPC local route) from a route table, e.g. a "
        "wrong or blackhole route that overrides the right one.",
        input_schema={
            "type": "object",
            "properties": {
                "route_table_id": {"type": "string", "pattern": "^rtb-[0-9a-f]+$"},
                "destination_cidr": {"type": "string"},
            },
            "required": ["route_table_id", "destination_cidr"],
            "additionalProperties": False,
        },
        write_actions=["ec2:DeleteRoute", "ec2:CreateRoute"],
        snapshot=_route_snapshot,
        precheck=_delete_precheck,
        preview=_delete_preview,
        execute=lambda read, write, p, s: _write(read, write, p, s, "delete_route", _gone(p)),
        verify=_route_verify(False),
        undo=lambda read, write, p, s, r: write.client("ec2").create_route(**_old(p, s)),
        undo_description=lambda p, s: f"Create the route {p['destination_cidr']} again",
        dry_run=lambda read, write, p, s: expect_dry_run(
            write.client("ec2").delete_route, **_gone(p)
        ),
    ),
    extra_reads=_EXTRA_READS,
)


# ---- route table association ---------------------------------------------------------


def effective_route_table(ec2, subnet_id: str, vpc_id: str) -> tuple[dict, str | None]:
    """(route table, explicit association id or None when the main table applies)."""
    tables = ec2.describe_route_tables(
        Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
    )["RouteTables"]
    for rt in tables:
        for a in rt.get("Associations", []):
            if a.get("SubnetId") == subnet_id:
                return rt, a["RouteTableAssociationId"]
    main = ec2.describe_route_tables(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "association.main", "Values": ["true"]},
        ]
    )["RouteTables"][0]
    return main, None


def _rt_snapshot(read: Session, p: dict) -> dict:
    ec2 = read.client("ec2")
    subnet = ec2.describe_subnets(SubnetIds=[p["subnet_id"]])["Subnets"][0]
    current, assoc = effective_route_table(ec2, p["subnet_id"], subnet["VpcId"])
    target = _table(ec2, p["route_table_id"])
    return {
        "subnet_id": p["subnet_id"],
        "vpc_id": subnet["VpcId"],
        "current_route_table_id": current["RouteTableId"],
        "explicit": assoc is not None,
        "current_routes": routes(current),
        "target": {
            "route_table_id": target["RouteTableId"],
            "vpc_id": target["VpcId"],
            "routes": routes(target),
            "igw_default": has_igw_default(target),
        },
    }


def _rt_precheck(p: dict, s: dict) -> str | None:
    if s["target"]["vpc_id"] != s["vpc_id"]:
        return f"{p['route_table_id']} is in {s['target']['vpc_id']}, not in the subnet's VPC"
    if s["current_route_table_id"] == p["route_table_id"]:
        return f"{p['subnet_id']} already uses {p['route_table_id']}"
    return None


def _rt_undo_description(p: dict, s: dict) -> str:
    if s["explicit"]:
        return f"Associate {p['subnet_id']} back with {s['current_route_table_id']}"
    return f"Remove the association so {p['subnet_id']} uses the VPC main table again"


def _rt_preview(p: dict, s: dict) -> dict:
    before = s["current_route_table_id"] + ("" if s["explicit"] else " (VPC main table)")
    public = s["target"]["igw_default"]
    return preview(
        f"Associate {p['subnet_id']} with route table {p['route_table_id']}",
        [
            {
                "field": f"Route table of {p['subnet_id']}",
                "before": f"{before}: {', '.join(s['current_routes'])}",
                "after": f"{p['route_table_id']}: {', '.join(s['target']['routes'])}",
            }
        ],
        f"Every instance in {p['subnet_id']} uses the routes of {p['route_table_id']}"
        + (
            " (0.0.0.0/0 -> Internet gateway: the subnet is public)."
            if public
            else " (no 0.0.0.0/0 route to an Internet gateway: the subnet is not public)."
        ),
        "medium",
        _rt_undo_description(p, s),
        f"The effective route table of {p['subnet_id']} is {p['route_table_id']}.",
    )


def _rt_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    current, assoc = effective_route_table(read.client("ec2"), p["subnet_id"], s["vpc_id"])
    ec2 = write.client("ec2")
    if assoc:
        new = ec2.replace_route_table_association(
            AssociationId=assoc, RouteTableId=p["route_table_id"]
        )["NewAssociationId"]
    else:
        new = ec2.associate_route_table(RouteTableId=p["route_table_id"], SubnetId=p["subnet_id"])[
            "AssociationId"
        ]
    return {"association_id": new, "previous_route_table_id": current["RouteTableId"]}


def _rt_dry_run(read: Session, write: Session, p: dict, s: dict) -> None:
    _, assoc = effective_route_table(read.client("ec2"), p["subnet_id"], s["vpc_id"])
    ec2 = write.client("ec2")
    if assoc:
        expect_dry_run(
            ec2.replace_route_table_association,
            AssociationId=assoc,
            RouteTableId=p["route_table_id"],
        )
    else:
        expect_dry_run(
            ec2.associate_route_table, RouteTableId=p["route_table_id"], SubnetId=p["subnet_id"]
        )


def _rt_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    rt, _ = effective_route_table(read.client("ec2"), p["subnet_id"], s["vpc_id"])
    ok = rt["RouteTableId"] == p["route_table_id"]
    return ok, f"{p['subnet_id']} uses {rt['RouteTableId']}: {', '.join(routes(rt))}"


def _rt_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    _, assoc = effective_route_table(read.client("ec2"), p["subnet_id"], s["vpc_id"])
    ec2 = write.client("ec2")
    if s["explicit"]:
        ec2.replace_route_table_association(
            AssociationId=assoc, RouteTableId=s["current_route_table_id"]
        )
    elif assoc:
        ec2.disassociate_route_table(AssociationId=assoc)


register(
    ActionSpec(
        name="route_table_associate",
        group="Route table",
        label="Change subnet route table",
        description="Make a subnet use another route table of its VPC, e.g. back to the "
        "public table (0.0.0.0/0 -> igw) after it was moved to a private one, or to a table "
        "with a NAT route.",
        input_schema={
            "type": "object",
            "properties": {
                "subnet_id": {"type": "string", "pattern": "^subnet-[0-9a-f]+$"},
                "route_table_id": {"type": "string", "pattern": "^rtb-[0-9a-f]+$"},
            },
            "required": ["subnet_id", "route_table_id"],
            "additionalProperties": False,
        },
        write_actions=[
            "ec2:AssociateRouteTable",
            "ec2:ReplaceRouteTableAssociation",
            "ec2:DisassociateRouteTable",
        ],
        snapshot=_rt_snapshot,
        precheck=_rt_precheck,
        preview=_rt_preview,
        execute=_rt_execute,
        verify=_rt_verify,
        undo=_rt_undo,
        undo_description=_rt_undo_description,
        dry_run=_rt_dry_run,
    )
)
