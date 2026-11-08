"""DNS group: Route 53 records and public DNS resolution."""

import logging
import re

import boto3
import dns.exception
import dns.resolver
from botocore.exceptions import BotoCoreError, ClientError

from app.aws.registry import ToolContext, tool
from app.aws.tools._common import MAX_ITEMS_SCHEMA, cap
from app.config import get_settings

log = logging.getLogger(__name__)

PUBLIC_RESOLVERS = ["8.8.8.8", "1.1.1.1"]

HOSTNAME_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b", re.I)


def hostnames_in(text: str) -> set[str]:
    return {m.group(0).lower().rstrip(".") for m in HOSTNAME_RE.finditer(text or "")}


def _zone_name(zone: dict) -> str:
    return zone["Name"].rstrip(".").lower()


def _related(hostname: str, name: str) -> bool:
    """Same name, a subdomain of it or one of its parents (app.x.com ~ x.com ~ a.app.x.com)."""
    return hostname == name or hostname.endswith("." + name) or name.endswith("." + hostname)


def hostname_allowed(session: boto3.Session, hostname: str, ctx: ToolContext) -> bool:
    """Only resolve names that come from the user or from the account's configuration.

    A prompt injected through a log line could otherwise make the agent leak data by
    looking up ``<data>.attacker.example``: the attacker's DNS server sees the query.
    """
    if any(_related(hostname, name) for name in hostnames_in(ctx.user_text)):
        return True
    if hostname in ctx.known_hostnames:
        return True
    try:
        for page in session.client("route53").get_paginator("list_hosted_zones").paginate():
            for zone in page["HostedZones"]:
                name = _zone_name(zone)
                if hostname == name or hostname.endswith("." + name):
                    return True
    except (ClientError, BotoCoreError) as e:
        log.info("Could not list hosted zones for the DNS guard: %s", e)
    return False


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
        matching = [
            z for z in zones if domain == _zone_name(z) or domain.endswith("." + _zone_name(z))
        ]
        # Longest suffix wins (sub.example.com over example.com); on a tie prefer the public
        # zone, which is what the Internet resolves.
        zones = sorted(
            matching,
            key=lambda z: (-len(_zone_name(z)), z.get("Config", {}).get("PrivateZone", False)),
        )[:1]

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
                        "zone": _zone_name(z),
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
        "zones": [_zone_name(z) for z in zones],
        "records": items,
        "_truncated": truncated,
    }


@tool(
    name="resolve_dns_public",
    group="dns",
    label="Public DNS lookup",
    description="Resolve a hostname using public resolvers (8.8.8.8, 1.1.1.1) to see what the "
    "Internet actually sees. Compare with the instance's current public IP. rcode NXDOMAIN "
    "means the name does not exist publicly; NODATA means no record of that type. Only names "
    "the user mentioned (and their parents/subdomains), names in the account's Route 53 "
    "hosted zones, or DNS names read from Route 53 records / load balancers can be resolved.",
    input_schema={
        "type": "object",
        "properties": {
            "hostname": {"type": "string"},
            "record_type": {"type": "string", "enum": ["A", "AAAA", "CNAME", "NS", "TXT"]},
        },
        "required": ["hostname"],
    },
    aws_actions=["route53:ListHostedZones"],
    context=True,
)
def resolve_dns_public(session: boto3.Session, params: dict, ctx: ToolContext) -> dict:
    hostname = (params.get("hostname") or "").strip().rstrip(".").lower()
    rtype = (params.get("record_type") or "A").upper()
    if not hostname:
        return {"error": "hostname is required"}
    if not hostname_allowed(session, hostname, ctx):
        return {
            "error": "HOSTNAME_NOT_ALLOWED: only names the user mentioned, names in the "
            "account's Route 53 hosted zones, or DNS names read from Route 53 records / load "
            "balancers can be resolved"
        }
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = get_settings().dns_resolver_list or PUBLIC_RESOLVERS
    resolver.lifetime = 5.0
    base = {"hostname": hostname, "type": rtype}
    try:
        answer = resolver.resolve(hostname, rtype)
    except dns.resolver.NXDOMAIN:
        # A finding, not a failure: the name does not exist in public DNS.
        return {**base, "rcode": "NXDOMAIN", "answers": []}
    except dns.resolver.NoAnswer:
        return {**base, "rcode": "NODATA", "answers": []}
    except (dns.exception.DNSException, OSError) as e:
        return {**base, "answers": [], "error": f"DNS error: {e}"}
    cname = answer.canonical_name.to_text().rstrip(".")
    return {
        **base,
        "rcode": "NOERROR",
        "answers": [r.to_text().strip('"') for r in answer],
        "canonical_name": cname if cname != hostname else None,
        "ttl": answer.rrset.ttl if answer.rrset is not None else None,
    }
