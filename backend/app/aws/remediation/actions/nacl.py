"""Network ACL entries and subnet associations."""

from app.aws.remediation.base import (
    DIRECTION,
    PORT,
    PROTOCOL,
    ActionSpec,
    Session,
    cidr_problem,
    expect_dry_run,
    is_world,
    network,
    opens_sensitive_port,
    port_problem,
    preview,
    register,
)

_PROTO = {"tcp": "6", "udp": "17", "icmp": "1", "all": "-1"}
_PROTO_NAME = {v: k for k, v in _PROTO.items()}


def _entry(e: dict) -> dict:
    """Normalised NACL entry (same shape as the action's parameters)."""
    proto = _PROTO_NAME.get(str(e.get("Protocol")), str(e.get("Protocol")))
    ports = e.get("PortRange") or {}
    return {
        "rule_number": e["RuleNumber"],
        "direction": "egress" if e.get("Egress") else "ingress",
        "rule_action": e.get("RuleAction"),
        "protocol": proto,
        "from_port": ports.get("From") if proto in ("tcp", "udp") else None,
        "to_port": ports.get("To") if proto in ("tcp", "udp") else None,
        "cidr": str(network(e.get("CidrBlock") or e.get("Ipv6CidrBlock"))),
    }


def _wanted(p: dict) -> dict:
    proto = p.get("protocol", "tcp")
    tcp_udp = proto in ("tcp", "udp")
    frm = p.get("from_port") if tcp_udp else None
    return {
        "rule_number": p["rule_number"],
        "direction": p.get("direction", "ingress"),
        "rule_action": p.get("rule_action", "allow"),
        "protocol": proto,
        "from_port": frm,
        "to_port": p.get("to_port", frm) if tcp_udp else None,
        "cidr": str(network(p["cidr"])),
    }


def _label(e: dict) -> str:
    ports = "" if e["from_port"] is None else f"/{e['from_port']}-{e['to_port']}"
    rule = f"{e['direction']} {e['rule_action']} {e['protocol']}{ports}"
    return f"#{e['rule_number']} {rule} {e['cidr']}"


def _acl(ec2, network_acl_id: str) -> dict:
    return ec2.describe_network_acls(NetworkAclIds=[network_acl_id])["NetworkAcls"][0]


def _find(acl: dict, rule_number: int, direction: str) -> dict | None:
    for e in acl.get("Entries", []):
        if e["RuleNumber"] == rule_number and bool(e.get("Egress")) == (direction == "egress"):
            return _entry(e)
    return None


def _entries(acl: dict) -> list[str]:
    return sorted(_label(_entry(e)) for e in acl.get("Entries", []))


def _snapshot(read: Session, p: dict) -> dict:
    acl = _acl(read.client("ec2"), p["network_acl_id"])
    return {
        "network_acl_id": acl["NetworkAclId"],
        "vpc_id": acl["VpcId"],
        "entry": _find(acl, p["rule_number"], p.get("direction", "ingress")),
        "_entries": _entries(acl),
    }


def _value_problem(p: dict) -> str | None:
    if problem := cidr_problem(p["cidr"]):
        return problem
    w = _wanted(p)
    if problem := port_problem(w["protocol"], w["from_port"], w["to_port"]):
        return problem
    if (
        w["direction"] == "ingress"
        and w["rule_action"] == "allow"
        and is_world(w["cidr"])
        and opens_sensitive_port(w["protocol"], w["from_port"], w["to_port"])
    ):
        return (
            "SSH / RDP (22, 3389) are never opened to the whole Internet; allow the user's own "
            "IP (/32) instead"
        )
    return None


def _add_precheck(p: dict, s: dict) -> str | None:
    if problem := _value_problem(p):
        return problem
    if s["entry"]:
        return f"Rule {_label(s['entry'])} already exists; use nacl_replace_entry"
    return None


def _replace_precheck(p: dict, s: dict) -> str | None:
    if problem := _value_problem(p):
        return problem
    if not s["entry"]:
        return (
            f"{p['network_acl_id']} has no {p.get('direction', 'ingress')} rule #{p['rule_number']}"
        )
    if s["entry"] == _wanted(p):
        return f"Rule {_label(s['entry'])} already has these values"
    return None


def _delete_precheck(p: dict, s: dict) -> str | None:
    if not s["entry"]:
        return (
            f"{p['network_acl_id']} has no {p.get('direction', 'ingress')} rule #{p['rule_number']}"
        )
    return None


def _kwargs(network_acl_id: str, e: dict) -> dict:
    net = network(e["cidr"])
    kwargs = {
        "NetworkAclId": network_acl_id,
        "RuleNumber": e["rule_number"],
        "Egress": e["direction"] == "egress",
        "RuleAction": e["rule_action"],
        "Protocol": _PROTO.get(e["protocol"], e["protocol"]),
        ("CidrBlock" if net.version == 4 else "Ipv6CidrBlock"): str(net),
    }
    if e["protocol"] in ("tcp", "udp"):
        kwargs["PortRange"] = {"From": e["from_port"], "To": e["to_port"]}
    if e["protocol"] == "icmp":
        kwargs["IcmpTypeCode"] = {"Type": -1, "Code": -1}
    return kwargs


def _key(p: dict) -> dict:
    return {
        "NetworkAclId": p["network_acl_id"],
        "RuleNumber": p["rule_number"],
        "Egress": p.get("direction", "ingress") == "egress",
    }


def _call(write: Session, verb: str, kwargs: dict, dry: bool = False) -> dict:
    fn = getattr(write.client("ec2"), f"{verb}_network_acl_entry")
    if dry:
        expect_dry_run(fn, **kwargs)
    else:
        fn(**kwargs)
    return {}


def _verify(expected):
    def verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
        acl = _acl(read.client("ec2"), p["network_acl_id"])
        now = _find(acl, p["rule_number"], p.get("direction", "ingress"))
        return now == expected(p), f"{p['network_acl_id']}: {', '.join(_entries(acl))}"

    return verify


def _change(p: dict, s: dict, after: str) -> list[dict]:
    before = _label(s["entry"]) if s["entry"] else "none"
    return [
        {
            "field": f"{p.get('direction', 'ingress').capitalize()} rule #{p['rule_number']} of "
            f"{p['network_acl_id']}",
            "before": before,
            "after": after,
        }
    ]


_IMPACT = (
    "Network ACLs are stateless and checked in rule-number order (lowest first) for every "
    "subnet associated with {acl}; return traffic needs its own rule."
)

_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "network_acl_id": {"type": "string", "pattern": "^acl-[0-9a-f]+$"},
        "rule_number": {"type": "integer", "minimum": 1, "maximum": 32766},
        "direction": DIRECTION,
        "rule_action": {"type": "string", "enum": ["allow", "deny"]},
        "protocol": PROTOCOL,
        "from_port": PORT,
        "to_port": PORT,
        "cidr": {"type": "string", "description": "e.g. 0.0.0.0/0"},
    },
    "required": ["network_acl_id", "rule_number", "cidr"],
    "additionalProperties": False,
}

register(
    ActionSpec(
        name="nacl_add_entry",
        group="Network ACL",
        label="Add network ACL rule",
        description="Add a numbered rule to a network ACL: direction ingress/egress, "
        "rule_action allow/deny, protocol, port range (tcp/udp), cidr. Rules are evaluated "
        "lowest number first and are stateless (return traffic on ephemeral ports 1024-65535 "
        "needs its own rule).",
        input_schema=_ENTRY_SCHEMA,
        write_actions=["ec2:CreateNetworkAclEntry", "ec2:DeleteNetworkAclEntry"],
        snapshot=_snapshot,
        precheck=_add_precheck,
        preview=lambda p, s: preview(
            f"Add rule {_label(_wanted(p))} to {p['network_acl_id']}",
            _change(p, s, _label(_wanted(p))),
            _IMPACT.format(acl=p["network_acl_id"]),
            "medium",
            f"Delete rule #{p['rule_number']} again",
            f"{p['network_acl_id']} has rule {_label(_wanted(p))}.",
        ),
        execute=lambda read, write, p, s: _call(
            write, "create", _kwargs(p["network_acl_id"], _wanted(p))
        ),
        verify=_verify(_wanted),
        undo=lambda read, write, p, s, r: _call(write, "delete", _key(p)),
        undo_description=lambda p, s: f"Delete rule #{p['rule_number']} from {p['network_acl_id']}",
        dry_run=lambda read, write, p, s: _call(
            write, "create", _kwargs(p["network_acl_id"], _wanted(p)), dry=True
        ),
    )
)

register(
    ActionSpec(
        name="nacl_replace_entry",
        group="Network ACL",
        label="Change network ACL rule",
        description="Change an EXISTING numbered rule of a network ACL (same parameters as "
        "nacl_add_entry), e.g. an egress deny on 1024-65535 that blocks return traffic -> allow.",
        input_schema=_ENTRY_SCHEMA,
        write_actions=["ec2:ReplaceNetworkAclEntry"],
        snapshot=_snapshot,
        precheck=_replace_precheck,
        preview=lambda p, s: preview(
            f"Change rule #{p['rule_number']} of {p['network_acl_id']} to {_label(_wanted(p))}",
            _change(p, s, _label(_wanted(p))),
            _IMPACT.format(acl=p["network_acl_id"]),
            "medium",
            f"Set rule #{p['rule_number']} back to {_label(s['entry'])}",
            f"{p['network_acl_id']} has rule {_label(_wanted(p))}.",
        ),
        execute=lambda read, write, p, s: _call(
            write, "replace", _kwargs(p["network_acl_id"], _wanted(p))
        ),
        verify=_verify(_wanted),
        undo=lambda read, write, p, s, r: _call(
            write, "replace", _kwargs(p["network_acl_id"], s["entry"])
        ),
        undo_description=lambda p, s: f"Set rule #{p['rule_number']} back to {_label(s['entry'])}",
        dry_run=lambda read, write, p, s: _call(
            write, "replace", _kwargs(p["network_acl_id"], _wanted(p)), dry=True
        ),
    )
)

register(
    ActionSpec(
        name="nacl_delete_entry",
        group="Network ACL",
        label="Delete network ACL rule",
        description="Delete ONE numbered rule (1-32766; never the default * rule) from a "
        "network ACL, e.g. a deny rule that blocks needed traffic.",
        input_schema={
            "type": "object",
            "properties": {
                "network_acl_id": {"type": "string", "pattern": "^acl-[0-9a-f]+$"},
                "rule_number": {"type": "integer", "minimum": 1, "maximum": 32766},
                "direction": DIRECTION,
            },
            "required": ["network_acl_id", "rule_number"],
            "additionalProperties": False,
        },
        write_actions=["ec2:DeleteNetworkAclEntry", "ec2:CreateNetworkAclEntry"],
        snapshot=_snapshot,
        precheck=_delete_precheck,
        preview=lambda p, s: preview(
            f"Delete rule {_label(s['entry'])} from {p['network_acl_id']}",
            _change(p, s, "none"),
            _IMPACT.format(acl=p["network_acl_id"]),
            "medium",
            f"Create rule {_label(s['entry'])} again",
            f"{p['network_acl_id']} has no {p.get('direction', 'ingress')} rule "
            f"#{p['rule_number']}.",
        ),
        execute=lambda read, write, p, s: _call(write, "delete", _key(p)),
        verify=_verify(lambda p: None),
        undo=lambda read, write, p, s, r: _call(
            write, "create", _kwargs(p["network_acl_id"], s["entry"])
        ),
        undo_description=lambda p, s: f"Create rule {_label(s['entry'])} again",
        dry_run=lambda read, write, p, s: _call(write, "delete", _key(p), dry=True),
    )
)


# ---- subnet association --------------------------------------------------------------


def _association(ec2, subnet_id: str) -> tuple[str, str]:
    """(network ACL id, association id) of a subnet: every subnet has exactly one."""
    acls = ec2.describe_network_acls(
        Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
    )["NetworkAcls"]
    for acl in acls:
        for a in acl.get("Associations", []):
            if a.get("SubnetId") == subnet_id:
                return acl["NetworkAclId"], a["NetworkAclAssociationId"]
    raise RuntimeError(f"No network ACL association found for {subnet_id}")


def _assoc_snapshot(read: Session, p: dict) -> dict:
    ec2 = read.client("ec2")
    subnet = ec2.describe_subnets(SubnetIds=[p["subnet_id"]])["Subnets"][0]
    current, _ = _association(ec2, p["subnet_id"])
    target = _acl(ec2, p["network_acl_id"])
    return {
        "subnet_id": p["subnet_id"],
        "vpc_id": subnet["VpcId"],
        "current_network_acl_id": current,
        "target_vpc_id": target["VpcId"],
        "_current_entries": _entries(_acl(ec2, current)),
        "_target_entries": _entries(target),
    }


def _assoc_precheck(p: dict, s: dict) -> str | None:
    if s["target_vpc_id"] != s["vpc_id"]:
        return f"{p['network_acl_id']} is in {s['target_vpc_id']}, not in the subnet's VPC"
    if s["current_network_acl_id"] == p["network_acl_id"]:
        return f"{p['subnet_id']} already uses {p['network_acl_id']}"
    return None


def _associate(read: Session, write: Session, subnet_id: str, acl_id: str, dry: bool = False):
    _, assoc = _association(read.client("ec2"), subnet_id)
    fn = write.client("ec2").replace_network_acl_association
    if dry:
        expect_dry_run(fn, AssociationId=assoc, NetworkAclId=acl_id)
        return {}
    return {"association_id": fn(AssociationId=assoc, NetworkAclId=acl_id)["NewAssociationId"]}


def _assoc_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    current, _ = _association(read.client("ec2"), p["subnet_id"])
    return current == p["network_acl_id"], f"{p['subnet_id']} uses {current}"


register(
    ActionSpec(
        name="nacl_associate",
        group="Network ACL",
        label="Change subnet network ACL",
        description="Make a subnet use another network ACL of its VPC, e.g. back to the "
        "default ACL after it was moved to a restrictive one.",
        input_schema={
            "type": "object",
            "properties": {
                "subnet_id": {"type": "string", "pattern": "^subnet-[0-9a-f]+$"},
                "network_acl_id": {"type": "string", "pattern": "^acl-[0-9a-f]+$"},
            },
            "required": ["subnet_id", "network_acl_id"],
            "additionalProperties": False,
        },
        write_actions=["ec2:ReplaceNetworkAclAssociation"],
        snapshot=_assoc_snapshot,
        precheck=_assoc_precheck,
        preview=lambda p, s: preview(
            f"Associate {p['subnet_id']} with network ACL {p['network_acl_id']}",
            [
                {
                    "field": f"Network ACL of {p['subnet_id']}",
                    "before": f"{s['current_network_acl_id']}: {', '.join(s['_current_entries'])}",
                    "after": f"{p['network_acl_id']}: {', '.join(s['_target_entries'])}",
                }
            ],
            f"Every instance in {p['subnet_id']} is filtered by the rules of "
            f"{p['network_acl_id']}.",
            "medium",
            f"Associate {p['subnet_id']} back with {s['current_network_acl_id']}",
            f"{p['subnet_id']} uses {p['network_acl_id']}.",
        ),
        execute=lambda read, write, p, s: _associate(
            read, write, p["subnet_id"], p["network_acl_id"]
        ),
        verify=_assoc_verify,
        undo=lambda read, write, p, s, r: _associate(
            read, write, p["subnet_id"], s["current_network_acl_id"]
        ),
        undo_description=lambda p, s: (
            f"Associate {p['subnet_id']} back with {s['current_network_acl_id']}"
        ),
        dry_run=lambda read, write, p, s: _associate(
            read, write, p["subnet_id"], p["network_acl_id"], dry=True
        ),
    )
)
