"""DNS group: Route 53 records and public DNS resolution."""

import boto3
import dns.exception
import dns.resolver

from app.aws.registry import tool
from app.aws.tools._common import MAX_ITEMS_SCHEMA, cap

PUBLIC_RESOLVERS = ["8.8.8.8", "1.1.1.1"]


@tool(
    name="route53_list_records",
    group="dns",
    label="Route 53 records",
    description="DNS records in Route 53 hosted zones. Give a domain to pick the matching zone "
    "and filter records to that name; otherwise lists records of all zones.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "e.g. app.example.com"},
            "zone_id": {"type": "string", "description": "Hosted zone id (optional)"},
            "max_items": MAX_ITEMS_SCHEMA,
        },
    },
    aws_actions=["route53:ListHostedZones", "route53:ListResourceRecordSets"],
)
def route53_list_records(session: boto3.Session, params: dict) -> dict:
    r53 = session.client("route53")
    domain = (params.get("domain") or "").rstrip(".").lower()
    zones = []
    for page in r53.get_paginator("list_hosted_zones").paginate():
        zones.extend(page["HostedZones"])
    if params.get("zone_id"):
        zones = [z for z in zones if z["Id"].endswith(params["zone_id"])]
    elif domain:
        matching = [z for z in zones if domain.endswith(z["Name"].rstrip(".").lower())]
        # Longest-suffix match wins (sub.example.com over example.com)
        zones = sorted(matching, key=lambda z: -len(z["Name"]))[:1]

    records = []
    for z in zones:
        for page in r53.get_paginator("list_resource_record_sets").paginate(HostedZoneId=z["Id"]):
            for rr in page["ResourceRecordSets"]:
                name = rr["Name"].rstrip(".").lower()
                if domain and name != domain:
                    continue
                alias = rr.get("AliasTarget")
                records.append(
                    {
                        "zone": z["Name"].rstrip("."),
                        "private_zone": z.get("Config", {}).get("PrivateZone", False),
                        "name": name,
                        "type": rr["Type"],
                        "ttl": rr.get("TTL"),
                        "values": [r["Value"] for r in rr.get("ResourceRecords", [])],
                        "alias_target": alias.get("DNSName") if alias else None,
                    }
                )
    items, truncated = cap(records, params)
    return {
        "zones": [z["Name"].rstrip(".") for z in zones],
        "records": items,
        "_truncated": truncated,
    }


@tool(
    name="resolve_dns_public",
    group="dns",
    label="Public DNS lookup",
    description="Resolve a hostname using public resolvers (8.8.8.8, 1.1.1.1) to see what the "
    "Internet actually sees. Compare with the instance's current public IP.",
    input_schema={
        "type": "object",
        "properties": {
            "hostname": {"type": "string"},
            "record_type": {"type": "string", "enum": ["A", "AAAA", "CNAME", "NS", "TXT"]},
        },
        "required": ["hostname"],
    },
    aws_actions=[],
)
def resolve_dns_public(session: boto3.Session, params: dict) -> dict:
    hostname = (params.get("hostname") or "").strip().rstrip(".")
    rtype = (params.get("record_type") or "A").upper()
    if not hostname:
        return {"error": "hostname is required"}
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = PUBLIC_RESOLVERS
    resolver.lifetime = 5.0
    try:
        answer = resolver.resolve(hostname, rtype)
        values = [r.to_text().strip('"') for r in answer]
        cname = answer.canonical_name.to_text().rstrip(".")
        return {
            "hostname": hostname,
            "type": rtype,
            "answers": values,
            "canonical_name": cname if cname != hostname else None,
            "ttl": answer.rrset.ttl if answer.rrset is not None else None,
        }
    except dns.resolver.NXDOMAIN:
        return {"hostname": hostname, "type": rtype, "answers": [], "error": "NXDOMAIN"}
    except dns.resolver.NoAnswer:
        return {"hostname": hostname, "type": rtype, "answers": [], "error": "No answer"}
    except (dns.exception.DNSException, OSError) as e:
        return {"hostname": hostname, "type": rtype, "answers": [], "error": f"DNS error: {e}"}
