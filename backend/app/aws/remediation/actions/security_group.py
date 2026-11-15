"""Security group rules: add or remove ONE rule (inbound or outbound)."""

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

_IP_PROTOCOL = {"tcp": "tcp", "udp": "udp", "icmp": "icmp", "all": "-1"}
_WRITES = [
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:RevokeSecurityGroupIngress",
    "ec2:RevokeSecurityGroupEgress",
]


def _direction(p: dict) -> str:
    return p.get("direction", "ingress")


def _ports(p: dict) -> tuple[int | None, int | None]:
    proto = p.get("protocol", "tcp")
    if proto == "all":
        return None, None
    if proto == "icmp":
        return p.get("from_port", -1), p.get("to_port", -1)
    frm = p.get("from_port")
    return frm, p.get("to_port", frm)


def _ip_protocol(p: dict) -> str:
    proto = _IP_PROTOCOL[p.get("protocol", "tcp")]
    if proto == "icmp" and p.get("cidr") and network(p["cidr"]).version == 6:
        return "icmpv6"
    return proto


def _key(proto: str, frm, to, src: str) -> str:
    if proto == "-1":
        frm = to = None  # "all traffic" has no port range (AWS omits it or says -1)
    return f"{proto}:{frm}-{to}:{src}"


def _source(p: dict) -> str:
    return p.get("source_group_id") or str(network(p["cidr"]))


def _rule_key(p: dict) -> str:
    frm, to = _ports(p)
    return _key(_ip_protocol(p), frm, to, _source(p))


def _permission(p: dict, description: str | None = None) -> dict:
    """The IpPermissions entry of the rule (description only when adding)."""
    frm, to = _ports(p)
    perm: dict = {"IpProtocol": _ip_protocol(p)}
    if frm is not None:
        perm["FromPort"], perm["ToPort"] = frm, to
    if p.get("source_group_id"):
        pair = {"GroupId": p["source_group_id"]}
        if description:
            pair["Description"] = description[:255]
        perm["UserIdGroupPairs"] = [pair]
    else:
        net = network(p["cidr"])
        key, field = ("IpRanges", "CidrIp") if net.version == 4 else ("Ipv6Ranges", "CidrIpv6")
        item = {field: str(net)}
        if description:
            item["Description"] = description[:255]
        perm[key] = [item]
    return perm


def _rules(permissions: list[dict]) -> dict[str, str]:
    """{rule key: description} of one direction of a group."""
    out: dict[str, str] = {}
    for perm in permissions:
        sources = [(r["CidrIp"], r.get("Description", "")) for r in perm.get("IpRanges", [])]
        sources += [(r["CidrIpv6"], r.get("Description", "")) for r in perm.get("Ipv6Ranges", [])]
        sources += [
            (g["GroupId"], g.get("Description", "")) for g in perm.get("UserIdGroupPairs", [])
        ]
        for src, desc in sources:
            key = _key(perm.get("IpProtocol"), perm.get("FromPort"), perm.get("ToPort"), src)
            out[key] = desc
    return out


def _snapshot(read: Session, p: dict) -> dict:
    ec2 = read.client("ec2")
    group = ec2.describe_security_groups(GroupIds=[p["group_id"]])["SecurityGroups"][0]
    snap = {
        "group_id": group["GroupId"],
        "vpc_id": group.get("VpcId"),
        "ingress": _rules(group.get("IpPermissions", [])),
        "egress": _rules(group.get("IpPermissionsEgress", [])),
    }
    if p.get("source_group_id"):  # must exist and be readable
        src = ec2.describe_security_groups(GroupIds=[p["source_group_id"]])["SecurityGroups"][0]
        snap["source_vpc_id"] = src.get("VpcId")
    return snap


def _rule_problem(p: dict) -> str | None:
    if bool(p.get("cidr")) == bool(p.get("source_group_id")):
        return "Give exactly one of cidr or source_group_id"
    if p.get("cidr") and (problem := cidr_problem(p["cidr"])):
        return problem
    proto = p.get("protocol", "tcp")
    frm, to = _ports(p)
    if problem := port_problem(proto, frm, to):
        return problem
    return None


def _describe(p: dict) -> str:
    proto = p.get("protocol", "tcp")
    frm, to = _ports(p)
    ports = "" if frm is None else (f"/{frm}" if frm == to else f"/{frm}-{to}")
    if proto == "icmp":
        ports = ""
    way = "from" if _direction(p) == "ingress" else "to"
    return f"{_direction(p)} {proto}{ports} {way} {_source(p)}"


def _add_precheck(p: dict, s: dict) -> str | None:
    if problem := _rule_problem(p):
        return problem
    if s.get("source_vpc_id") and s["source_vpc_id"] != s["vpc_id"]:
        return f"{p['source_group_id']} is in another VPC"
    frm, to = _ports(p)
    if (
        _direction(p) == "ingress"
        and is_world(p.get("cidr"))
        and opens_sensitive_port(p.get("protocol", "tcp"), frm, to)
    ):
        return (
            "SSH / RDP (22, 3389) are never opened to the whole Internet; use the user's own "
            "IP (/32) or Session Manager instead"
        )
    if _rule_key(p) in s[_direction(p)]:
        return f"{p['group_id']} already has the rule {_describe(p)}"
    return None


def _remove_precheck(p: dict, s: dict) -> str | None:
    if problem := _rule_problem(p):
        return problem
    if _rule_key(p) not in s[_direction(p)]:
        return f"{p['group_id']} has no rule {_describe(p)}"
    return None


def _call(write: Session, verb: str, p: dict, dry: bool = False, description: str | None = None):
    ec2 = write.client("ec2")
    name = f"{verb}_security_group_{_direction(p)}"
    kwargs = {"GroupId": p["group_id"], "IpPermissions": [_permission(p, description)]}
    if dry:
        expect_dry_run(getattr(ec2, name), **kwargs)
        return None
    return getattr(ec2, name)(**kwargs)


def _listing(rules: dict[str, str]) -> str:
    return ", ".join(sorted(rules)) or "none"


def _add_preview(p: dict, s: dict) -> dict:
    rule = _describe(p)
    return preview(
        f"Add rule {rule} to {p['group_id']}",
        [
            {
                "field": f"{_direction(p).capitalize()} rules of {p['group_id']}",
                "before": _listing(s[_direction(p)]),
                "after": ", ".join(sorted([*s[_direction(p)], _rule_key(p)])),
            }
        ],
        f"Every network interface using {p['group_id']} allows {rule}.",
        "medium" if is_world(p.get("cidr")) else "low",
        f"Remove the rule {rule} from {p['group_id']}",
        f"{p['group_id']} lists the new rule.",
    )


def _remove_preview(p: dict, s: dict) -> dict:
    rule = _describe(p)
    rules = s[_direction(p)]
    return preview(
        f"Remove rule {rule} from {p['group_id']}",
        [
            {
                "field": f"{_direction(p).capitalize()} rules of {p['group_id']}",
                "before": _listing(rules),
                "after": _listing({k: v for k, v in rules.items() if k != _rule_key(p)}),
            }
        ],
        f"Traffic matching {rule} is no longer allowed for {p['group_id']}; existing "
        "connections tracked by the group may continue.",
        "medium",
        f"Add the rule {rule} back to {p['group_id']}",
        f"{p['group_id']} no longer lists the rule.",
    )


def _add_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    resp = _call(write, "authorize", p, description=p.get("description"))
    return {"rule_ids": [r["SecurityGroupRuleId"] for r in resp.get("SecurityGroupRules", [])]}


def _remove_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    _call(write, "revoke", p)
    return {"description": s[_direction(p)].get(_rule_key(p), "")}


def _verify(present: bool):
    def verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
        now = _snapshot(read, p)[_direction(p)]
        return (_rule_key(p) in now) == present, f"{p['group_id']} {_direction(p)}: {_listing(now)}"

    return verify


register(
    ActionSpec(
        name="sg_add_rule",
        group="Security Group",
        label="Add security group rule",
        description="Add ONE rule to a security group: inbound (ingress) or outbound (egress), "
        "protocol tcp/udp/icmp/all, a port range (from_port..to_port, to_port defaults to "
        "from_port) and ONE source/destination: cidr or source_group_id. Never SSH/RDP "
        "(22, 3389, or protocol all) inbound from 0.0.0.0/0 or ::/0: use the user's IP /32.",
        input_schema={
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "pattern": "^sg-[0-9a-f]+$"},
                "direction": DIRECTION,
                "protocol": PROTOCOL,
                "from_port": PORT,
                "to_port": PORT,
                "cidr": {"type": "string", "description": "e.g. 0.0.0.0/0 or 203.0.113.7/32"},
                "source_group_id": {"type": "string", "pattern": "^sg-[0-9a-f]+$"},
                "description": {"type": "string", "maxLength": 255},
            },
            "required": ["group_id"],
            "additionalProperties": False,
        },
        write_actions=_WRITES,
        snapshot=_snapshot,
        precheck=_add_precheck,
        preview=_add_preview,
        execute=_add_execute,
        verify=_verify(True),
        undo=lambda read, write, p, s, r: _call(write, "revoke", p),
        undo_description=lambda p, s: f"Remove the new rule from {p['group_id']}",
        dry_run=lambda read, write, p, s: _call(
            write, "authorize", p, dry=True, description=p.get("description")
        ),
    )
)

register(
    ActionSpec(
        name="sg_remove_rule",
        group="Security Group",
        label="Remove security group rule",
        description="Remove ONE existing rule from a security group, identified exactly like "
        "sg_add_rule (direction, protocol, ports, cidr or source_group_id), e.g. an inbound "
        "22 from 0.0.0.0/0 that exposes SSH, or an outbound rule that is too broad.",
        input_schema={
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "pattern": "^sg-[0-9a-f]+$"},
                "direction": DIRECTION,
                "protocol": PROTOCOL,
                "from_port": PORT,
                "to_port": PORT,
                "cidr": {"type": "string"},
                "source_group_id": {"type": "string", "pattern": "^sg-[0-9a-f]+$"},
            },
            "required": ["group_id"],
            "additionalProperties": False,
        },
        write_actions=_WRITES,
        snapshot=_snapshot,
        precheck=_remove_precheck,
        preview=_remove_preview,
        execute=_remove_execute,
        verify=_verify(False),
        undo=lambda read, write, p, s, r: _call(
            write, "authorize", p, description=s[_direction(p)].get(_rule_key(p)) or None
        ),
        undo_description=lambda p, s: f"Add the removed rule back to {p['group_id']}",
        dry_run=lambda read, write, p, s: _call(write, "revoke", p, dry=True),
    )
)
