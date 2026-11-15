"""Route 53: create or update ONE record (A / AAAA / CNAME / TXT) in a hosted zone of the
account. A records may also be an alias to a load balancer of the account."""

import ipaddress
import re

from app.aws.remediation.actions.instance import instance
from app.aws.remediation.base import ActionSpec, Session, preview, register, wait_until

TYPES = ["A", "AAAA", "CNAME", "TXT"]
# CNAME targets outside the account's own zones must be AWS endpoints (no attacker domains)
_AWS_SUFFIXES = (".amazonaws.com", ".cloudfront.net", ".awsglobalaccelerator.com")
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9_]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _name(value: str) -> str:
    return value.rstrip(".").lower()


def zone_for(r53, name: str, zone_id: str | None) -> dict | None:
    zones = [
        z for page in r53.get_paginator("list_hosted_zones").paginate() for z in page["HostedZones"]
    ]
    if zone_id:
        return next((z for z in zones if z["Id"].endswith(zone_id)), None)
    matching = [
        z for z in zones if name == _name(z["Name"]) or name.endswith("." + _name(z["Name"]))
    ]
    matching.sort(key=lambda z: (-len(z["Name"]), z.get("Config", {}).get("PrivateZone", False)))
    return matching[0] if matching else None


def _records_at(r53, zone_id: str, name: str) -> list[dict]:
    resp = r53.list_resource_record_sets(HostedZoneId=zone_id, StartRecordName=name, MaxItems="20")
    return [rr for rr in resp["ResourceRecordSets"] if _name(rr["Name"]) == name]


def _norm(rr: dict | None) -> dict | None:
    if rr is None:
        return None
    alias = rr.get("AliasTarget")
    return {
        "ttl": rr.get("TTL"),
        "values": sorted(v["Value"] for v in rr.get("ResourceRecords", [])),
        "alias": None
        if not alias
        else {
            "dns_name": _name(alias["DNSName"]),
            "zone_id": alias["HostedZoneId"],
            "evaluate": bool(alias.get("EvaluateTargetHealth")),
        },
    }


def account_ips(read: Session) -> tuple[set[str], set[str]]:
    """(public IPv4, IPv6) addresses of the account's instances and Elastic IPs."""
    ec2 = read.client("ec2")
    v4 = {a["PublicIp"] for a in ec2.describe_addresses()["Addresses"]}
    v6: set[str] = set()
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                if inst.get("PublicIpAddress"):
                    v4.add(inst["PublicIpAddress"])
                for eni in inst.get("NetworkInterfaces", []):
                    v6 |= {
                        str(ipaddress.ip_address(a["Ipv6Address"]))
                        for a in eni.get("Ipv6Addresses", [])
                    }
    return v4, v6


def _load_balancer(read: Session, ref: str) -> dict:
    elb = read.client("elbv2")
    kwargs = {"LoadBalancerArns": [ref]} if ref.startswith("arn:") else {"Names": [ref]}
    lb = elb.describe_load_balancers(**kwargs)["LoadBalancers"][0]
    return {
        "name": lb["LoadBalancerName"],
        "dns_name": _name(lb["DNSName"]),
        "zone_id": lb["CanonicalHostedZoneId"],
    }


def _instance_ip(inst: dict, rtype: str) -> str | None:
    if rtype == "A":
        return inst.get("PublicIpAddress")
    for eni in inst.get("NetworkInterfaces", []):
        for a in eni.get("Ipv6Addresses", []):
            return str(ipaddress.ip_address(a["Ipv6Address"]))
    return None


def _snapshot(read: Session, p: dict) -> dict:
    name = _name(p["record_name"])
    rtype = p.get("type", "A")
    r53 = read.client("route53")
    zone = zone_for(r53, name, p.get("zone_id"))
    records = _records_at(r53, zone["Id"], name) if zone else []
    snap = {
        "record_name": name,
        "type": rtype,
        "zone_id": zone["Id"] if zone else None,
        "zone_name": _name(zone["Name"]) if zone else None,
        "record": _norm(next((rr for rr in records if rr["Type"] == rtype), None)),
        "other_types": sorted({rr["Type"] for rr in records if rr["Type"] != rtype}),
        "_zones": sorted(
            _name(z["Name"])
            for page in r53.get_paginator("list_hosted_zones").paginate()
            for z in page["HostedZones"]
        ),
    }
    if rtype in ("A", "AAAA"):
        v4, v6 = account_ips(read)
        snap["_account_ips"] = sorted(v4 if rtype == "A" else v6)
    if p.get("instance_id"):
        inst = instance(read, p["instance_id"])
        snap["_instance_state"] = inst["State"]["Name"]
        snap["_instance_ip"] = _instance_ip(inst, rtype)
    if p.get("load_balancer"):
        snap["load_balancer"] = _load_balancer(read, p["load_balancer"])
    return snap


def _txt(value: str) -> str:
    return value if value.startswith('"') else f'"{value}"'


def _desired(p: dict, s: dict, ip: str | None = None) -> dict:
    """Normalised record the change should produce (``ip``: for an instance target)."""
    rtype = s["type"]
    if p.get("load_balancer"):
        lb = s["load_balancer"]
        return {
            "ttl": None,
            "values": [],
            "alias": {"dns_name": lb["dns_name"], "zone_id": lb["zone_id"], "evaluate": False},
        }
    ttl = p.get("ttl") or (s["record"] or {}).get("ttl") or 300
    if p.get("instance_id"):
        value = ip or s.get("_instance_ip") or ""
    elif rtype == "TXT":
        value = _txt(p["value"])
    elif rtype == "CNAME":
        value = _name(p["value"])
    else:
        value = str(ipaddress.ip_address(p["value"]))
    return {"ttl": ttl, "values": [value], "alias": None}


def _precheck(p: dict, s: dict) -> str | None:
    rtype = s["type"]
    name = s["record_name"]
    if not s["zone_id"]:
        return f"No hosted zone of this account contains {name}"
    sources = [k for k in ("value", "instance_id", "load_balancer") if p.get(k)]
    if len(sources) != 1:
        return "Give exactly one of value, instance_id or load_balancer"
    if p.get("instance_id") and rtype not in ("A", "AAAA"):
        return "instance_id is only for A / AAAA records"
    if p.get("load_balancer") and rtype != "A":
        return "load_balancer (alias) is only for A records"
    if rtype == "CNAME":
        if name == s["zone_name"]:
            return "A CNAME cannot be at the zone apex; use an A alias (load_balancer)"
        if s["other_types"]:
            return (
                f"{name} already has {', '.join(s['other_types'])} records; a CNAME must be alone"
            )
    elif "CNAME" in s["other_types"]:
        return f"{name} is a CNAME; it cannot have {rtype} records too"
    if p.get("value"):
        value = p["value"].strip()
        if rtype in ("A", "AAAA"):
            try:
                ip = ipaddress.ip_address(value)
            except ValueError:
                return f"{value} is not an IP address"
            if (rtype == "A") != (ip.version == 4):
                return f"{value} is not an IPv{4 if rtype == 'A' else 6} address"
            if str(ip) not in s["_account_ips"]:
                return f"{value} is not an address of an instance or Elastic IP in this account"
        elif rtype == "CNAME":
            target = _name(value)
            if not _HOSTNAME.match(target):
                return f"{value} is not a host name"
            own = any(target == z or target.endswith("." + z) for z in s["_zones"])
            if not own and not target.endswith(_AWS_SUFFIXES):
                return (
                    f"{value} is neither an AWS endpoint nor a name in this account's hosted zones"
                )
        elif len(value) > 255 or '"' in value.strip('"'):
            return "A TXT value must be at most 255 characters, without quotes inside"
    if p.get("instance_id"):
        if s.get("_instance_state") != "running":
            return f"{p['instance_id']} is not running"
        if not s.get("_instance_ip"):
            return f"{p['instance_id']} has no {'public IPv4' if rtype == 'A' else 'IPv6'} address"
    if s["record"] and s["record"] == _desired(p, s):
        return f"{name} ({rtype}) already has this value"
    return None


def _show(record: dict | None) -> str:
    if record is None:
        return "none (new record)"
    if record["alias"]:
        return f"alias {record['alias']['dns_name']}"
    return f"{', '.join(record['values'])} (TTL {record['ttl']})"


def _preview(p: dict, s: dict) -> dict:
    target = p.get("load_balancer") or p.get("value") or p["instance_id"]
    after = _show(_desired(p, s))
    if p.get("instance_id"):
        after = (
            f"the {'public IPv4' if s['type'] == 'A' else 'IPv6'} of {p['instance_id']} at "
            f"execution time (now {s.get('_instance_ip')}; the Elastic IP if one is attached "
            "first)"
        )
    ttl = (s["record"] or {}).get("ttl")
    return preview(
        f"{'Update' if s['record'] else 'Create'} {s['record_name']} ({s['type']}) -> {target}",
        [
            {
                "field": f"{s['type']} record {s['record_name']}",
                "before": _show(s["record"]),
                "after": after,
            }
        ],
        f"Clients resolve {s['record_name']} to the new value"
        + (f" once cached answers expire (TTL {ttl} s)." if ttl else "."),
        "low",
        f"Set {s['record_name']} back to {_show(s['record'])}"
        if s["record"]
        else f"Delete the new record {s['record_name']}",
        "Route 53 returns the new value and the change is INSYNC (public resolvers may still "
        "cache the old value until the TTL expires).",
    )


def _rrset(name: str, rtype: str, record: dict) -> dict:
    rrset: dict = {"Name": name, "Type": rtype}
    if record["alias"]:
        rrset["AliasTarget"] = {
            "HostedZoneId": record["alias"]["zone_id"],
            "DNSName": record["alias"]["dns_name"],
            "EvaluateTargetHealth": record["alias"]["evaluate"],
        }
    else:
        rrset["TTL"] = record["ttl"]
        rrset["ResourceRecords"] = [{"Value": v} for v in record["values"]]
    return rrset


def _change(write: Session, s: dict, action: str, record: dict, comment: str) -> str:
    resp = write.client("route53").change_resource_record_sets(
        HostedZoneId=s["zone_id"],
        ChangeBatch={
            "Comment": comment,
            "Changes": [
                {"Action": action, "ResourceRecordSet": _rrset(s["record_name"], s["type"], record)}
            ],
        },
    )
    return resp["ChangeInfo"]["Id"]


def _execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    ip = None
    if p.get("instance_id"):
        ip = _instance_ip(instance(read, p["instance_id"]), s["type"])
        if not ip:
            raise RuntimeError(f"{p['instance_id']} has no address for a {s['type']} record")
    record = _desired(p, s, ip)
    change_id = _change(write, s, "UPSERT", record, "AutoAWS approved proposal")
    return {"record": record, "change_id": change_id}


def _current(read: Session, s: dict) -> dict | None:
    records = _records_at(read.client("route53"), s["zone_id"], s["record_name"])
    return _norm(next((rr for rr in records if rr["Type"] == s["type"]), None))


def _verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    r53 = read.client("route53")

    def check() -> tuple[bool, str]:
        now = _current(read, s)
        status = r53.get_change(Id=r["change_id"])["ChangeInfo"]["Status"]
        return now == r["record"] and status == "INSYNC", f"{_show(now)} ({status})"

    return wait_until(check)


def _undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    if s["record"] is not None:
        _change(write, s, "UPSERT", s["record"], "AutoAWS approved rollback")
        return
    now = _current(read, s)  # the record AutoAWS created: DELETE needs its exact values
    if now is not None:
        _change(write, s, "DELETE", now, "AutoAWS approved rollback (remove created record)")


register(
    ActionSpec(
        name="dns_upsert_record",
        group="Route 53",
        label="Create or update DNS record",
        description="Create or update ONE Route 53 record (type A, AAAA, CNAME or TXT) in a "
        "hosted zone of the account. Give exactly one of: value (A/AAAA: an IP of an "
        "instance / Elastic IP in this account; CNAME: an AWS endpoint or a name in the "
        "account's zones; TXT: text), instance_id (A/AAAA: its IP at execution time, use it "
        "after eip_allocate_and_associate) or load_balancer (A alias to an ALB/NLB of the "
        "account, name or ARN).",
        input_schema={
            "type": "object",
            "properties": {
                "record_name": {"type": "string", "description": "e.g. app.example.com"},
                "type": {"type": "string", "enum": TYPES},
                "value": {"type": "string", "maxLength": 255},
                "instance_id": {"type": "string", "pattern": "^i-[0-9a-f]+$"},
                "load_balancer": {"type": "string"},
                "ttl": {"type": "integer", "minimum": 60, "maximum": 86400},
                "zone_id": {"type": "string"},
            },
            "required": ["record_name"],
            "additionalProperties": False,
        },
        write_actions=["route53:ChangeResourceRecordSets"],
        snapshot=_snapshot,
        precheck=_precheck,
        preview=_preview,
        execute=_execute,
        verify=_verify,
        undo=_undo,
        undo_description=lambda p, s: (
            f"Set {s['record_name']} back to {_show(s['record'])}"
            if s["record"]
            else f"Delete the record {s['record_name']} created by AutoAWS"
        ),
    ),
    extra_reads=("route53:GetChange", "elasticloadbalancing:DescribeLoadBalancers"),
)
