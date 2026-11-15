"""Load balancer target groups: health check settings and registered targets."""

from app.aws.remediation.base import ActionSpec, Session, preview, register, wait_until

# parameter -> (target group field in DescribeTargetGroups / ModifyTargetGroup)
HEALTH_FIELDS = {
    "path": "HealthCheckPath",
    "port": "HealthCheckPort",
    "protocol": "HealthCheckProtocol",
    "matcher": "Matcher",
    "interval_seconds": "HealthCheckIntervalSeconds",
    "timeout_seconds": "HealthCheckTimeoutSeconds",
    "healthy_threshold": "HealthyThresholdCount",
    "unhealthy_threshold": "UnhealthyThresholdCount",
}


def target_group(read: Session, ref: str) -> dict:
    elb = read.client("elbv2")
    kwargs = {"TargetGroupArns": [ref]} if ref.startswith("arn:") else {"Names": [ref]}
    return elb.describe_target_groups(**kwargs)["TargetGroups"][0]


def _health(read: Session, arn: str) -> list[dict]:
    return read.client("elbv2").describe_target_health(TargetGroupArn=arn)[
        "TargetHealthDescriptions"
    ]


def _targets(health: list[dict]) -> list[str]:
    return [
        f"{d['Target']['Id']}:{d['Target'].get('Port')} {d['TargetHealth']['State']}"
        for d in health
    ]


def _settings(tg: dict) -> dict:
    out = {}
    for param, field in HEALTH_FIELDS.items():
        value = tg.get(field)
        if param == "matcher":
            value = (value or {}).get("HttpCode")
        out[param] = value
    return out


# ---- health check ------------------------------------------------------------------------


def _hc_snapshot(read: Session, p: dict) -> dict:
    tg = target_group(read, p["target_group"])
    return {
        "target_group_arn": tg["TargetGroupArn"],
        "name": tg["TargetGroupName"],
        "health_check": _settings(tg),
        "_targets": _targets(_health(read, tg["TargetGroupArn"])),
    }


def _changes(p: dict, s: dict) -> dict:
    """The health check settings the user asked to change (and that differ)."""
    current = s["health_check"]
    asked = {k: (str(p[k]) if k == "port" else p[k]) for k in HEALTH_FIELDS if k in p}
    return {k: v for k, v in asked.items() if v != current.get(k)}


def _hc_precheck(p: dict, s: dict) -> str | None:
    changes = _changes(p, s)
    if not changes:
        return f"{s['name']} already has these health check settings"
    after = {**s["health_check"], **changes}
    http = after["protocol"] in ("HTTP", "HTTPS")
    if "path" in changes and (not str(changes["path"]).startswith("/") or " " in changes["path"]):
        return f"{changes['path']!r} must start with / and contain no spaces"
    if not http and ("path" in changes or "matcher" in changes):
        return f"{s['name']} checks with {after['protocol']}: no HTTP path / matcher"
    port = str(after["port"])
    if port != "traffic-port" and not (port.isdigit() and 1 <= int(port) <= 65535):
        return f"Health check port {port} must be traffic-port or 1-65535"
    timeout, interval = after["timeout_seconds"], after["interval_seconds"]
    if timeout and interval and timeout >= interval:
        return "The health check timeout must be shorter than the interval"
    return None


def _modify(write: Session, arn: str, settings: dict) -> dict:
    kwargs = {"TargetGroupArn": arn}
    for param, value in settings.items():
        field = HEALTH_FIELDS[param]
        kwargs[field] = {"HttpCode": value} if param == "matcher" else value
    write.client("elbv2").modify_target_group(**kwargs)
    return {}


def _hc_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    changes = _changes(p, s)
    _modify(write, s["target_group_arn"], changes)
    return {"changes": changes}


def _hc_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    wanted = r["changes"]

    def check() -> tuple[bool, str]:
        now = _settings(target_group(read, s["target_group_arn"]))
        applied = all(now.get(k) == v for k, v in wanted.items())
        states = [d["TargetHealth"]["State"] for d in _health(read, s["target_group_arn"])]
        healthy = all(st == "healthy" for st in states)
        return applied and healthy, (
            f"settings {'applied' if applied else 'not applied'}; targets: "
            f"{', '.join(states) or 'none registered'}"
        )

    return wait_until(check)


def _hc_preview(p: dict, s: dict) -> dict:
    changes = _changes(p, s)
    return preview(
        f"Change the health check of {s['name']}: "
        + ", ".join(f"{k}={v}" for k, v in changes.items()),
        [
            {
                "field": f"Health check {k} of {s['name']}",
                "before": str(s["health_check"].get(k)),
                "after": str(v),
            }
            for k, v in changes.items()
        ],
        f"The load balancer checks every target with the new settings "
        f"({', '.join(s['_targets']) or 'no target registered'}).",
        "low",
        "Set the changed health check settings back",
        "The settings are applied and every registered target reports healthy (waits a few "
        "health check intervals).",
    )


register(
    ActionSpec(
        name="tg_modify_health_check",
        group="Load balancer",
        label="Change health check",
        description="Change the health check of a target group (name or ARN): any of path, "
        "port ('traffic-port' or a number), protocol (HTTP/HTTPS/TCP), matcher (HTTP codes, "
        "e.g. 200-399), interval_seconds, timeout_seconds, healthy_threshold, "
        "unhealthy_threshold. Only the given settings change.",
        input_schema={
            "type": "object",
            "properties": {
                "target_group": {"type": "string"},
                "path": {"type": "string", "maxLength": 1024},
                "port": {"type": "string", "pattern": "^(traffic-port|[0-9]{1,5})$"},
                "protocol": {"type": "string", "enum": ["HTTP", "HTTPS", "TCP"]},
                "matcher": {"type": "string", "pattern": "^[0-9]{3}([-,][0-9]{3})*$"},
                "interval_seconds": {"type": "integer", "minimum": 5, "maximum": 300},
                "timeout_seconds": {"type": "integer", "minimum": 2, "maximum": 120},
                "healthy_threshold": {"type": "integer", "minimum": 2, "maximum": 10},
                "unhealthy_threshold": {"type": "integer", "minimum": 2, "maximum": 10},
            },
            "required": ["target_group"],
            "additionalProperties": False,
        },
        write_actions=["elasticloadbalancing:ModifyTargetGroup"],
        snapshot=_hc_snapshot,
        precheck=_hc_precheck,
        preview=_hc_preview,
        execute=_hc_execute,
        verify=_hc_verify,
        undo=lambda read, write, p, s, r: _modify(
            write,
            s["target_group_arn"],
            {k: s["health_check"][k] for k in (r.get("changes") or _changes(p, s))},
        ),
        undo_description=lambda p, s: (
            "Set " + ", ".join(f"{k} back to {s['health_check'].get(k)}" for k in _changes(p, s))
        ),
    )
)


# ---- targets -------------------------------------------------------------------------------


def _target_key(target_id: str, port) -> str:
    return f"{target_id}:{port}"


def _targets_snapshot(read: Session, p: dict) -> dict:
    tg = target_group(read, p["target_group"])
    health = _health(read, tg["TargetGroupArn"])
    snap = {
        "target_group_arn": tg["TargetGroupArn"],
        "name": tg["TargetGroupName"],
        "target_type": tg.get("TargetType", "instance"),
        "vpc_id": tg.get("VpcId"),
        "port": tg.get("Port"),
        # targets being deregistered linger as "draining": they are no longer registered
        "registered": sorted(
            _target_key(d["Target"]["Id"], d["Target"].get("Port"))
            for d in health
            if d["TargetHealth"]["State"] != "draining"
        ),
        "_targets": _targets(health),
    }
    if p["target_id"].startswith("i-"):
        inst = read.client("ec2").describe_instances(InstanceIds=[p["target_id"]])["Reservations"][
            0
        ]["Instances"][0]
        snap["target_vpc_id"] = inst.get("VpcId")
    return snap


def _key(p: dict, s: dict) -> str:
    return _target_key(p["target_id"], p.get("port") or s["port"])


def _target(p: dict, s: dict) -> dict:
    target = {"Id": p["target_id"]}
    if s["target_type"] != "lambda":
        target["Port"] = p.get("port") or s["port"]
    return target


def _register_precheck(p: dict, s: dict) -> str | None:
    is_instance = p["target_id"].startswith("i-")
    if (s["target_type"] == "instance") != is_instance:
        return f"{s['name']} takes {s['target_type']} targets, not {p['target_id']}"
    if is_instance and s.get("target_vpc_id") != s["vpc_id"]:
        return f"{p['target_id']} is not in the VPC of {s['name']}"
    if _key(p, s) in s["registered"]:
        return f"{p['target_id']} is already registered in {s['name']}"
    return None


def _deregister_precheck(p: dict, s: dict) -> str | None:
    if _key(p, s) not in s["registered"]:
        return f"{p['target_id']} is not registered in {s['name']}"
    return None


def _set_target(write: Session, s: dict, p: dict, register_it: bool) -> dict:
    elb = write.client("elbv2")
    call = elb.register_targets if register_it else elb.deregister_targets
    call(TargetGroupArn=s["target_group_arn"], Targets=[_target(p, s)])
    return {}


def _targets_verify(registered: bool):
    def verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
        health = _health(read, s["target_group_arn"])
        state = next(
            (
                d["TargetHealth"]["State"]
                for d in health
                if _target_key(d["Target"]["Id"], d["Target"].get("Port")) == _key(p, s)
            ),
            None,
        )
        if registered:
            ok = state is not None and state not in ("unused", "draining")
        else:
            ok = state in (None, "draining")
        return ok, f"{p['target_id']} in {s['name']}: {state or 'not registered'}"

    return verify


_TARGET_SCHEMA = {
    "type": "object",
    "properties": {
        "target_group": {"type": "string"},
        "target_id": {"type": "string", "description": "instance id (i-...) or IP address"},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
    },
    "required": ["target_group", "target_id"],
    "additionalProperties": False,
}

register(
    ActionSpec(
        name="tg_register_target",
        group="Load balancer",
        label="Register target",
        description="Register a target (instance id in the same VPC, or IP) in a target group "
        "(name or ARN), on the group's port unless port is given.",
        input_schema=_TARGET_SCHEMA,
        write_actions=[
            "elasticloadbalancing:RegisterTargets",
            "elasticloadbalancing:DeregisterTargets",
        ],
        snapshot=_targets_snapshot,
        precheck=_register_precheck,
        preview=lambda p, s: preview(
            f"Register {p['target_id']} in {s['name']}",
            [
                {
                    "field": f"Targets of {s['name']}",
                    "before": ", ".join(s["registered"]) or "none",
                    "after": ", ".join(sorted([*s["registered"], _key(p, s)])),
                }
            ],
            f"The load balancer starts health checks on {p['target_id']} and sends it traffic "
            "once it is healthy.",
            "low",
            f"Deregister {p['target_id']} again",
            f"{p['target_id']} is registered in {s['name']}.",
        ),
        execute=lambda read, write, p, s: _set_target(write, s, p, True),
        verify=_targets_verify(True),
        undo=lambda read, write, p, s, r: _set_target(write, s, p, False),
        undo_description=lambda p, s: f"Deregister {p['target_id']} from {s['name']}",
    ),
    extra_reads=("ec2:DescribeInstances",),
)

register(
    ActionSpec(
        name="tg_deregister_target",
        group="Load balancer",
        label="Deregister target",
        description="Deregister a target from a target group (name or ARN), e.g. a broken "
        "instance that keeps receiving traffic. In-flight requests drain first.",
        input_schema=_TARGET_SCHEMA,
        write_actions=[
            "elasticloadbalancing:DeregisterTargets",
            "elasticloadbalancing:RegisterTargets",
        ],
        snapshot=_targets_snapshot,
        precheck=_deregister_precheck,
        preview=lambda p, s: preview(
            f"Deregister {p['target_id']} from {s['name']}",
            [
                {
                    "field": f"Targets of {s['name']}",
                    "before": ", ".join(s["registered"]) or "none",
                    "after": ", ".join(k for k in s["registered"] if k != _key(p, s)) or "none",
                }
            ],
            f"The load balancer stops sending new requests to {p['target_id']} (existing ones "
            "drain).",
            "medium",
            f"Register {p['target_id']} again",
            f"{p['target_id']} is draining or no longer registered in {s['name']}.",
        ),
        execute=lambda read, write, p, s: _set_target(write, s, p, False),
        verify=_targets_verify(False),
        undo=lambda read, write, p, s, r: _set_target(write, s, p, True),
        undo_description=lambda p, s: f"Register {p['target_id']} in {s['name']} again",
    ),
    extra_reads=("ec2:DescribeInstances",),
)
