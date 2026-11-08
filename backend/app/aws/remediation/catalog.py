"""Fixed catalogue of remediation actions (report Table 2.11, docs/API_CONTRACT.md §7).

Each action is plain code:

  snapshot(read, params)                      -> state of the target (read-only session)
  precheck(params, snapshot)                  -> problem text, or None
  preview(params, snapshot)                   -> what the user sees before approving
  execute(read, write, params, snapshot)      -> result (ids needed for undo)
  verify(read, params, snapshot, result)      -> (ok, details)
  undo(read, write, params, snapshot, result) -> None (back to the snapshot state)

Snapshot keys starting with "_" are display-only: they are not part of the hash used for the
STALE check and to confirm an undo restored the original state.

Writes happen only through ``write`` (a session locked to ``write_actions``); every read goes
through the read-only session. Nothing here deletes a user's resource, touches IAM or stops an
instance; undo only removes what the action itself created.
"""

import ipaddress
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import boto3

from app.config import get_settings

Session = boto3.Session

# Ports never opened to the whole Internet, whatever the model proposes.
_SENSITIVE_PORTS = {22, 3389}
_WORLD = {"0.0.0.0/0", "::/0"}


@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str
    description: str  # for the LLM
    input_schema: dict
    write_actions: list[str]  # what the AutoAWSRemediation role grants
    snapshot: Callable[[Session, dict], dict]
    precheck: Callable[[dict, dict], str | None]
    preview: Callable[[dict, dict], dict]
    execute: Callable[[Session, Session, dict, dict], dict]
    verify: Callable[[Session, dict, dict, dict], tuple[bool, str]]
    undo: Callable[[Session, Session, dict, dict, dict], None]
    undo_description: Callable[[dict, dict], str] = field(default=lambda p, s: "")


CATALOG: dict[str, ActionSpec] = {}

# Read calls the actions make outside the read tools (added to the read-only role policy).
EXTRA_READ_ACTIONS = ["route53:GetChange"]


def register(spec: ActionSpec) -> ActionSpec:
    if spec.name in CATALOG:
        raise ValueError(f"Duplicate remediation action {spec.name}")
    CATALOG[spec.name] = spec
    return spec


def get_action(name: str) -> ActionSpec | None:
    return CATALOG.get(name)


def all_write_actions() -> list[str]:
    return sorted({a for spec in CATALOG.values() for a in spec.write_actions})


def _preview(summary, changes, impact, risk, rollback, verify) -> dict:
    return {
        "summary": summary,
        "changes": changes,
        "impact": impact,
        "risk": risk,
        "rollback": rollback,
        "verify": verify,
    }


def _wait(check: Callable[[], tuple[bool, str]]) -> tuple[bool, str]:
    """Poll ``check`` until it passes or the verification timeout runs out."""
    settings = get_settings()
    deadline = time.monotonic() + settings.remediation_verify_timeout_seconds
    while True:
        ok, details = check()
        if ok or time.monotonic() >= deadline:
            return ok, details
        time.sleep(settings.remediation_verify_poll_seconds)


# ---- route tables ------------------------------------------------------------------


def _routes(rt: dict) -> list[str]:
    out = []
    for r in rt.get("Routes", []):
        dest = r.get("DestinationCidrBlock") or r.get("DestinationIpv6CidrBlock") or "?"
        target = r.get("GatewayId") or r.get("NatGatewayId") or r.get("NetworkInterfaceId") or "?"
        out.append(f"{dest} -> {target} ({r.get('State', 'active')})")
    return sorted(out)


def _has_igw_default(rt: dict) -> bool:
    return any(
        r.get("DestinationCidrBlock") == "0.0.0.0/0"
        and (r.get("GatewayId") or "").startswith("igw-")
        and r.get("State", "active") == "active"
        for r in rt.get("Routes", [])
    )


def _effective_route_table(ec2, subnet_id: str, vpc_id: str) -> tuple[dict, str | None]:
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
    current, assoc = _effective_route_table(ec2, p["subnet_id"], subnet["VpcId"])
    target = ec2.describe_route_tables(RouteTableIds=[p["route_table_id"]])["RouteTables"][0]
    return {
        "subnet_id": p["subnet_id"],
        "vpc_id": subnet["VpcId"],
        "current_route_table_id": current["RouteTableId"],
        "explicit": assoc is not None,
        "current_routes": _routes(current),
        "target": {
            "route_table_id": target["RouteTableId"],
            "vpc_id": target["VpcId"],
            "routes": _routes(target),
            "igw_default": _has_igw_default(target),
        },
    }


def _rt_precheck(p: dict, s: dict) -> str | None:
    if s["target"]["vpc_id"] != s["vpc_id"]:
        return f"{p['route_table_id']} is in {s['target']['vpc_id']}, not in the subnet's VPC"
    if not s["target"]["igw_default"]:
        return f"{p['route_table_id']} has no active 0.0.0.0/0 route to an Internet gateway"
    if s["current_route_table_id"] == p["route_table_id"]:
        return f"{p['subnet_id']} already uses {p['route_table_id']}"
    return None


def _rt_preview(p: dict, s: dict) -> dict:
    before = s["current_route_table_id"] + ("" if s["explicit"] else " (VPC main table)")
    return _preview(
        f"Associate {p['subnet_id']} with route table {p['route_table_id']}",
        [
            {
                "field": f"Route table of {p['subnet_id']}",
                "before": f"{before}: {', '.join(s['current_routes'])}",
                "after": f"{p['route_table_id']}: {', '.join(s['target']['routes'])}",
            }
        ],
        f"Every instance in {p['subnet_id']} uses the routes of {p['route_table_id']}.",
        "low",
        _rt_undo_description(p, s),
        f"The effective route table of {p['subnet_id']} has 0.0.0.0/0 to an Internet gateway.",
    )


def _rt_undo_description(p: dict, s: dict) -> str:
    if s["explicit"]:
        return f"Associate {p['subnet_id']} back with {s['current_route_table_id']}"
    return f"Remove the association so {p['subnet_id']} uses the VPC main table again"


def _rt_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    current, assoc = _effective_route_table(read.client("ec2"), p["subnet_id"], s["vpc_id"])
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


def _rt_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    rt, _ = _effective_route_table(read.client("ec2"), p["subnet_id"], s["vpc_id"])
    ok = rt["RouteTableId"] == p["route_table_id"] and _has_igw_default(rt)
    return ok, f"{p['subnet_id']} uses {rt['RouteTableId']}: {', '.join(_routes(rt))}"


def _rt_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    _, assoc = _effective_route_table(read.client("ec2"), p["subnet_id"], s["vpc_id"])
    ec2 = write.client("ec2")
    if s["explicit"]:
        ec2.replace_route_table_association(
            AssociationId=assoc, RouteTableId=s["current_route_table_id"]
        )
    elif assoc:
        ec2.disassociate_route_table(AssociationId=assoc)


register(
    ActionSpec(
        name="associate_route_table",
        label="Associate route table",
        description="Make a subnet use another route table of its VPC (one with an active "
        "0.0.0.0/0 route to an Internet gateway). Fixes a subnet that lost its Internet route "
        "because it was moved to a private route table.",
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
    )
)


def _route_snapshot(read: Session, p: dict) -> dict:
    ec2 = read.client("ec2")
    rt = ec2.describe_route_tables(RouteTableIds=[p["route_table_id"]])["RouteTables"][0]
    igws = ec2.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [rt["VpcId"]]}]
    )["InternetGateways"]
    default = [r for r in rt.get("Routes", []) if r.get("DestinationCidrBlock") == "0.0.0.0/0"]
    return {
        "route_table_id": rt["RouteTableId"],
        "vpc_id": rt["VpcId"],
        "routes": _routes(rt),
        "default_route": _routes({"Routes": default}),
        "attached_igws": sorted(
            g["InternetGatewayId"]
            for g in igws
            if any(a.get("State") in ("available", "attached") for a in g.get("Attachments", []))
        ),
    }


def _route_igw(p: dict, s: dict) -> str | None:
    if p.get("internet_gateway_id"):
        return p["internet_gateway_id"]
    return s["attached_igws"][0] if len(s["attached_igws"]) == 1 else None


def _route_precheck(p: dict, s: dict) -> str | None:
    if s["default_route"]:
        return f"{p['route_table_id']} already has a 0.0.0.0/0 route: {s['default_route'][0]}"
    igw = _route_igw(p, s)
    if not igw:
        return f"No single Internet gateway attached to {s['vpc_id']}; give internet_gateway_id"
    if igw not in s["attached_igws"]:
        return f"{igw} is not attached to {s['vpc_id']}"
    return None


def _route_preview(p: dict, s: dict) -> dict:
    igw = _route_igw(p, s)
    return _preview(
        f"Add route 0.0.0.0/0 -> {igw} to {p['route_table_id']}",
        [
            {
                "field": f"Routes of {p['route_table_id']}",
                "before": ", ".join(s["routes"]),
                "after": ", ".join([*s["routes"], f"0.0.0.0/0 -> {igw} (active)"]),
            }
        ],
        f"Every subnet using {p['route_table_id']} becomes public (reachable through {igw}).",
        "medium",
        f"Delete the 0.0.0.0/0 route from {p['route_table_id']}",
        f"{p['route_table_id']} has an active 0.0.0.0/0 route to {igw}.",
    )


def _route_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    igw = _route_igw(p, s)
    write.client("ec2").create_route(
        RouteTableId=p["route_table_id"], DestinationCidrBlock="0.0.0.0/0", GatewayId=igw
    )
    return {"gateway_id": igw}


def _route_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    rt = read.client("ec2").describe_route_tables(RouteTableIds=[p["route_table_id"]])[
        "RouteTables"
    ][0]
    ok = _has_igw_default(rt)
    return ok, f"{p['route_table_id']}: {', '.join(_routes(rt))}"


def _route_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    write.client("ec2").delete_route(
        RouteTableId=p["route_table_id"], DestinationCidrBlock="0.0.0.0/0"
    )


register(
    ActionSpec(
        name="create_route_to_igw",
        label="Add route to Internet gateway",
        description="Add a 0.0.0.0/0 route to the VPC's Internet gateway in a route table that "
        "has no default route. Makes every subnet of that table public.",
        input_schema={
            "type": "object",
            "properties": {
                "route_table_id": {"type": "string", "pattern": "^rtb-[0-9a-f]+$"},
                "internet_gateway_id": {"type": "string", "pattern": "^igw-[0-9a-f]+$"},
            },
            "required": ["route_table_id"],
            "additionalProperties": False,
        },
        write_actions=["ec2:CreateRoute", "ec2:DeleteRoute"],
        snapshot=_route_snapshot,
        precheck=_route_precheck,
        preview=_route_preview,
        execute=_route_execute,
        verify=_route_verify,
        undo=_route_undo,
        undo_description=lambda p, s: f"Delete the 0.0.0.0/0 route from {p['route_table_id']}",
    )
)


# ---- security group ----------------------------------------------------------------


def _permission(p: dict) -> dict:
    net = ipaddress.ip_network(p["cidr"], strict=False)
    ranges = {"CidrIp": str(net)} if net.version == 4 else {"CidrIpv6": str(net)}
    if p.get("description"):
        ranges["Description"] = p["description"][:255]
    key = "IpRanges" if net.version == 4 else "Ipv6Ranges"
    return {
        "IpProtocol": p.get("protocol", "tcp"),
        "FromPort": p["port"],
        "ToPort": p["port"],
        key: [ranges],
    }


def _rule_key(proto: str, frm, to, src: str) -> str:
    return f"{proto}:{frm}-{to}:{src}"


def _sg_rules(group: dict) -> list[str]:
    out = []
    for perm in group.get("IpPermissions", []):
        sources = [r["CidrIp"] for r in perm.get("IpRanges", [])]
        sources += [r["CidrIpv6"] for r in perm.get("Ipv6Ranges", [])]
        sources += [g["GroupId"] for g in perm.get("UserIdGroupPairs", [])]
        for src in sources:
            out.append(
                _rule_key(perm.get("IpProtocol"), perm.get("FromPort"), perm.get("ToPort"), src)
            )
    return sorted(out)


def _sg_snapshot(read: Session, p: dict) -> dict:
    group = read.client("ec2").describe_security_groups(GroupIds=[p["group_id"]])["SecurityGroups"][
        0
    ]
    return {"group_id": group["GroupId"], "vpc_id": group.get("VpcId"), "inbound": _sg_rules(group)}


def _sg_new_rule(p: dict) -> str:
    net = ipaddress.ip_network(p["cidr"], strict=False)
    return _rule_key(p.get("protocol", "tcp"), p["port"], p["port"], str(net))


def _sg_precheck(p: dict, s: dict) -> str | None:
    try:
        net = ipaddress.ip_network(p["cidr"], strict=False)
    except ValueError:
        return f"{p['cidr']} is not a valid CIDR"
    if p["port"] in _SENSITIVE_PORTS and str(net) in _WORLD:
        return (
            f"Port {p['port']} is never opened to the whole Internet; use the user's own IP "
            "(/32) or Session Manager instead"
        )
    if _sg_new_rule(p) in s["inbound"]:
        return f"{p['group_id']} already allows {p.get('protocol', 'tcp')}/{p['port']} from {net}"
    return None


def _sg_preview(p: dict, s: dict) -> dict:
    net = ipaddress.ip_network(p["cidr"], strict=False)
    rule = f"inbound {p.get('protocol', 'tcp')}/{p['port']} from {net}"
    return _preview(
        f"Allow {rule} in {p['group_id']}",
        [
            {
                "field": f"Inbound rules of {p['group_id']}",
                "before": ", ".join(s["inbound"]) or "none",
                "after": ", ".join(sorted([*s["inbound"], _sg_new_rule(p)])),
            }
        ],
        f"Every instance using {p['group_id']} accepts {rule}.",
        "medium" if str(net) in _WORLD else "low",
        f"Revoke {rule} from {p['group_id']}",
        f"{p['group_id']} lists the new rule.",
    )


def _sg_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    resp = write.client("ec2").authorize_security_group_ingress(
        GroupId=p["group_id"], IpPermissions=[_permission(p)]
    )
    return {"rule_ids": [r["SecurityGroupRuleId"] for r in resp.get("SecurityGroupRules", [])]}


def _sg_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    now = _sg_snapshot(read, p)["inbound"]
    return _sg_new_rule(p) in now, f"{p['group_id']} inbound: {', '.join(now)}"


def _sg_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    write.client("ec2").revoke_security_group_ingress(
        GroupId=p["group_id"], IpPermissions=[_permission(p)]
    )


register(
    ActionSpec(
        name="authorize_sg_ingress",
        label="Allow inbound port",
        description="Add ONE inbound rule (one port, one CIDR) to a security group, e.g. TCP "
        "8080 from 0.0.0.0/0 for a public web app. Never 22 or 3389 from 0.0.0.0/0 or "
        "::/0 (refused): for SSH/RDP use the user's own IP /32.",
        input_schema={
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "pattern": "^sg-[0-9a-f]+$"},
                "protocol": {"type": "string", "enum": ["tcp", "udp"]},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "cidr": {"type": "string", "description": "e.g. 0.0.0.0/0 or 203.0.113.7/32"},
                "description": {"type": "string", "maxLength": 255},
            },
            "required": ["group_id", "port", "cidr"],
            "additionalProperties": False,
        },
        write_actions=["ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress"],
        snapshot=_sg_snapshot,
        precheck=_sg_precheck,
        preview=_sg_preview,
        execute=_sg_execute,
        verify=_sg_verify,
        undo=_sg_undo,
        undo_description=lambda p, s: f"Revoke the new rule from {p['group_id']}",
    )
)


# ---- Elastic IP (KB2, KB5) ---------------------------------------------------------------


def _instance(read: Session, instance_id: str) -> dict:
    return read.client("ec2").describe_instances(InstanceIds=[instance_id])["Reservations"][0][
        "Instances"
    ][0]


def _eips_of(read: Session, instance_id: str) -> list[str]:
    addresses = read.client("ec2").describe_addresses(
        Filters=[{"Name": "instance-id", "Values": [instance_id]}]
    )["Addresses"]
    return sorted(a["PublicIp"] for a in addresses)


def _eip_snapshot(read: Session, p: dict) -> dict:
    inst = _instance(read, p["instance_id"])
    return {
        "instance_id": p["instance_id"],
        "state": inst["State"]["Name"],
        "elastic_ips": _eips_of(read, p["instance_id"]),
        # a dynamic public IP changes on its own (stop/start, EIP release): display only
        "_public_ip": inst.get("PublicIpAddress"),
    }


def _eip_precheck(p: dict, s: dict) -> str | None:
    if s["state"] != "running":
        return f"{p['instance_id']} is {s['state']}, not running"
    if s["elastic_ips"]:
        return f"{p['instance_id']} already has Elastic IP {s['elastic_ips'][0]}"
    return None


def _eip_preview(p: dict, s: dict) -> dict:
    return _preview(
        f"Allocate an Elastic IP and attach it to {p['instance_id']}",
        [
            {
                "field": f"Public IP of {p['instance_id']}",
                "before": f"{s['_public_ip'] or 'none'} (changes on every stop/start)",
                "after": "a new Elastic IP (stays the same across stop/start)",
            }
        ],
        "The instance's public IP changes now to the Elastic IP; update DNS records that point "
        "to the old IP (upsert_a_record with instance_id does it). An unattached Elastic IP "
        "costs money; attached to a running instance it is billed like any public IPv4.",
        "low",
        "Detach and release the Elastic IP",
        f"The public IP of {p['instance_id']} equals the new Elastic IP.",
    )


def _eip_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    ec2 = write.client("ec2")
    alloc = ec2.allocate_address(Domain="vpc")
    try:
        assoc = ec2.associate_address(
            AllocationId=alloc["AllocationId"], InstanceId=p["instance_id"]
        )
    except Exception:
        ec2.release_address(AllocationId=alloc["AllocationId"])  # do not leave a billed EIP
        raise
    return {
        "allocation_id": alloc["AllocationId"],
        "association_id": assoc["AssociationId"],
        "public_ip": alloc["PublicIp"],
    }


def _eip_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    ip = _instance(read, p["instance_id"]).get("PublicIpAddress")
    return ip == r["public_ip"], f"{p['instance_id']} public IP {ip}, Elastic IP {r['public_ip']}"


def _eip_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    ec2 = write.client("ec2")
    ec2.disassociate_address(AssociationId=r["association_id"])
    ec2.release_address(AllocationId=r["allocation_id"])


register(
    ActionSpec(
        name="allocate_and_associate_eip",
        label="Attach Elastic IP",
        description="Allocate a new Elastic IP and attach it to a running instance that has "
        "none, so its public IP survives stop/start or it gets one at all.",
        input_schema={
            "type": "object",
            "properties": {"instance_id": {"type": "string", "pattern": "^i-[0-9a-f]+$"}},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        write_actions=[
            "ec2:AllocateAddress",
            "ec2:AssociateAddress",
            "ec2:DisassociateAddress",
            "ec2:ReleaseAddress",
        ],
        snapshot=_eip_snapshot,
        precheck=_eip_precheck,
        preview=_eip_preview,
        execute=_eip_execute,
        verify=_eip_verify,
        undo=_eip_undo,
        undo_description=lambda p, s: "Detach and release the Elastic IP",
    )
)


# ---- Route 53 A record --------------------------------------------------------------


def _zone_for(r53, name: str, zone_id: str | None) -> dict | None:
    zones = [
        z for page in r53.get_paginator("list_hosted_zones").paginate() for z in page["HostedZones"]
    ]
    if zone_id:
        return next((z for z in zones if z["Id"].endswith(zone_id)), None)
    matching = [
        z
        for z in zones
        if name == z["Name"].rstrip(".").lower()
        or name.endswith("." + z["Name"].rstrip(".").lower())
    ]
    matching.sort(key=lambda z: (-len(z["Name"]), z.get("Config", {}).get("PrivateZone", False)))
    return matching[0] if matching else None


def _a_record(r53, zone_id: str, name: str) -> dict | None:
    resp = r53.list_resource_record_sets(
        HostedZoneId=zone_id, StartRecordName=name, StartRecordType="A", MaxItems="1"
    )
    for rr in resp["ResourceRecordSets"]:
        if rr["Name"].rstrip(".").lower() == name and rr["Type"] == "A":
            return rr
    return None


def _account_ips(read: Session) -> set[str]:
    ec2 = read.client("ec2")
    ips = {a["PublicIp"] for a in ec2.describe_addresses()["Addresses"]}
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page["Reservations"]:
            ips |= {i["PublicIpAddress"] for i in res["Instances"] if i.get("PublicIpAddress")}
    return ips


def _dns_snapshot(read: Session, p: dict) -> dict:
    name = p["record_name"].rstrip(".").lower()
    r53 = read.client("route53")
    zone = _zone_for(r53, name, p.get("zone_id"))
    record = _a_record(r53, zone["Id"], name) if zone else None
    snap = {
        "record_name": name,
        "zone_id": zone["Id"] if zone else None,
        "exists": record is not None and "AliasTarget" not in record,
        "values": sorted(v["Value"] for v in (record or {}).get("ResourceRecords", [])),
        "ttl": (record or {}).get("TTL"),
        "_account_ips": sorted(_account_ips(read)),
    }
    if p.get("instance_id"):
        inst = _instance(read, p["instance_id"])
        snap["_instance_state"] = inst["State"]["Name"]
        snap["_instance_ip"] = inst.get("PublicIpAddress")
    return snap


def _dns_precheck(p: dict, s: dict) -> str | None:
    if bool(p.get("ip")) == bool(p.get("instance_id")):
        return "Give exactly one of ip or instance_id"
    if not s["zone_id"]:
        return f"No hosted zone of this account contains {s['record_name']}"
    if not s["exists"]:
        return f"{s['record_name']} has no A record to update (new records are not created)"
    if p.get("ip"):
        try:
            ipaddress.IPv4Address(p["ip"])
        except ValueError:
            return f"{p['ip']} is not an IPv4 address"
        if p["ip"] not in s["_account_ips"]:
            return f"{p['ip']} is not a public IP of an instance or Elastic IP in this account"
        if [p["ip"]] == s["values"]:
            return f"{s['record_name']} already points to {p['ip']}"
    elif s.get("_instance_state") != "running":
        return f"{p['instance_id']} is not running"
    return None


def _dns_target(p: dict, s: dict) -> str:
    if p.get("ip"):
        return p["ip"]
    return (
        f"the public IP of {p['instance_id']} at execution time (now {s.get('_instance_ip')}; "
        "the Elastic IP if one is attached first)"
    )


def _dns_preview(p: dict, s: dict) -> dict:
    return _preview(
        f"Point {s['record_name']} (A) to {p.get('ip') or p['instance_id']}",
        [
            {
                "field": f"A record {s['record_name']}",
                "before": ", ".join(s["values"]),
                "after": _dns_target(p, s),
            }
        ],
        f"Clients resolve {s['record_name']} to the new IP once cached answers expire "
        f"(TTL {s['ttl']} s).",
        "low",
        f"Set {s['record_name']} back to {', '.join(s['values'])}",
        "Route 53 returns the new value and the change is INSYNC (public resolvers may still "
        "cache the old IP until the TTL expires).",
    )


def _dns_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    ip = p.get("ip") or _instance(read, p["instance_id"]).get("PublicIpAddress")
    if not ip:
        raise RuntimeError(f"{p['instance_id']} has no public IP")
    change = write.client("route53").change_resource_record_sets(
        HostedZoneId=s["zone_id"],
        ChangeBatch={
            "Comment": "AutoAWS approved proposal",
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": s["record_name"],
                        "Type": "A",
                        "TTL": s["ttl"] or 300,
                        "ResourceRecords": [{"Value": ip}],
                    },
                }
            ],
        },
    )
    return {"value": ip, "change_id": change["ChangeInfo"]["Id"]}


def _dns_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    r53 = read.client("route53")

    def check() -> tuple[bool, str]:
        record = _a_record(r53, s["zone_id"], s["record_name"]) or {}
        values = [v["Value"] for v in record.get("ResourceRecords", [])]
        status = r53.get_change(Id=r["change_id"])["ChangeInfo"]["Status"]
        return values == [r["value"]] and status == "INSYNC", f"{values} ({status})"

    return _wait(check)


def _dns_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    write.client("route53").change_resource_record_sets(
        HostedZoneId=s["zone_id"],
        ChangeBatch={
            "Comment": "AutoAWS approved rollback",
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": s["record_name"],
                        "Type": "A",
                        "TTL": s["ttl"] or 300,
                        "ResourceRecords": [{"Value": v} for v in s["values"]],
                    },
                }
            ],
        },
    )


register(
    ActionSpec(
        name="upsert_a_record",
        label="Update DNS A record",
        description="Point an EXISTING Route 53 A record of the account to a new IP: either "
        "`ip` (a public IP of an instance / Elastic IP in this account) or `instance_id` (its "
        "public IP at execution time — use this after allocate_and_associate_eip).",
        input_schema={
            "type": "object",
            "properties": {
                "record_name": {"type": "string", "description": "e.g. app.example.com"},
                "ip": {"type": "string"},
                "instance_id": {"type": "string", "pattern": "^i-[0-9a-f]+$"},
                "zone_id": {"type": "string"},
            },
            "required": ["record_name"],
            "additionalProperties": False,
        },
        write_actions=["route53:ChangeResourceRecordSets"],
        snapshot=_dns_snapshot,
        precheck=_dns_precheck,
        preview=_dns_preview,
        execute=_dns_execute,
        verify=_dns_verify,
        undo=_dns_undo,
        undo_description=lambda p, s: f"Set the record back to {', '.join(s['values'])}",
    )
)


# ---- target group health check ------------------------------------------------------


def _tg(read: Session, ref: str) -> dict:
    elb = read.client("elbv2")
    kwargs = {"TargetGroupArns": [ref]} if ref.startswith("arn:") else {"Names": [ref]}
    return elb.describe_target_groups(**kwargs)["TargetGroups"][0]


def _tg_snapshot(read: Session, p: dict) -> dict:
    tg = _tg(read, p["target_group"])
    health = read.client("elbv2").describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
    return {
        "target_group_arn": tg["TargetGroupArn"],
        "name": tg["TargetGroupName"],
        "protocol": tg.get("Protocol"),
        "health_check_path": tg.get("HealthCheckPath"),
        "_interval": tg.get("HealthCheckIntervalSeconds"),
        "_targets": [
            f"{d['Target']['Id']}: {d['TargetHealth']['State']}"
            for d in health["TargetHealthDescriptions"]
        ],
    }


def _tg_precheck(p: dict, s: dict) -> str | None:
    path = p["path"]
    if not path.startswith("/") or " " in path:
        return f"{path!r} must start with / and contain no spaces"
    if s["protocol"] not in ("HTTP", "HTTPS"):
        return f"{s['name']} uses {s['protocol']}: no HTTP health check path"
    if path == s["health_check_path"]:
        return f"{s['name']} already checks {path}"
    return None


def _tg_preview(p: dict, s: dict) -> dict:
    return _preview(
        f"Change the health check path of {s['name']} to {p['path']}",
        [
            {
                "field": f"Health check path of {s['name']}",
                "before": s["health_check_path"],
                "after": p["path"],
            }
        ],
        f"The load balancer checks {p['path']} on every target ({', '.join(s['_targets'])}).",
        "low",
        f"Set the health check path back to {s['health_check_path']}",
        "Every registered target reports healthy (waits a few health check intervals).",
    )


def _tg_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    write.client("elbv2").modify_target_group(
        TargetGroupArn=s["target_group_arn"], HealthCheckPath=p["path"]
    )
    return {"previous_path": s["health_check_path"]}


def _tg_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    elb = read.client("elbv2")

    def check() -> tuple[bool, str]:
        states = [
            d["TargetHealth"]["State"]
            for d in elb.describe_target_health(TargetGroupArn=s["target_group_arn"])[
                "TargetHealthDescriptions"
            ]
        ]
        path = _tg(read, s["target_group_arn"]).get("HealthCheckPath")
        ok = path == p["path"] and bool(states) and all(st == "healthy" for st in states)
        return ok, f"path {path}; targets: {', '.join(states) or 'none registered'}"

    return _wait(check)


def _tg_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    write.client("elbv2").modify_target_group(
        TargetGroupArn=s["target_group_arn"], HealthCheckPath=s["health_check_path"]
    )


register(
    ActionSpec(
        name="modify_health_check_path",
        label="Change health check path",
        description="Change the HTTP health check path of a target group, e.g. /health -> "
        "/api/health after a release renamed the endpoint. `target_group` is its name "
        "or ARN.",
        input_schema={
            "type": "object",
            "properties": {
                "target_group": {"type": "string"},
                "path": {"type": "string", "maxLength": 1024},
            },
            "required": ["target_group", "path"],
            "additionalProperties": False,
        },
        write_actions=["elasticloadbalancing:ModifyTargetGroup"],
        snapshot=_tg_snapshot,
        precheck=_tg_precheck,
        preview=_tg_preview,
        execute=_tg_execute,
        verify=_tg_verify,
        undo=_tg_undo,
        undo_description=lambda p, s: f"Set the path back to {s['health_check_path']}",
    )
)
