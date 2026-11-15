"""Subnet public IP setting, instances (start, security groups) and Elastic IPs."""

from app.aws.remediation.base import (
    ActionSpec,
    Session,
    expect_dry_run,
    preview,
    register,
    wait_until,
)

_INSTANCE_ID = {"type": "string", "pattern": "^i-[0-9a-f]+$"}


def instance(read: Session, instance_id: str) -> dict:
    return read.client("ec2").describe_instances(InstanceIds=[instance_id])["Reservations"][0][
        "Instances"
    ][0]


def elastic_ips_of(read: Session, instance_id: str) -> list[str]:
    addresses = read.client("ec2").describe_addresses(
        Filters=[{"Name": "instance-id", "Values": [instance_id]}]
    )["Addresses"]
    return sorted(a["PublicIp"] for a in addresses)


# ---- subnet: auto-assign public IPv4 ----------------------------------------------------


def _subnet_snapshot(read: Session, p: dict) -> dict:
    subnet = read.client("ec2").describe_subnets(SubnetIds=[p["subnet_id"]])["Subnets"][0]
    return {
        "subnet_id": subnet["SubnetId"],
        "map_public_ip_on_launch": bool(subnet.get("MapPublicIpOnLaunch")),
    }


def _set_subnet(write: Session, subnet_id: str, value: bool) -> dict:
    write.client("ec2").modify_subnet_attribute(
        SubnetId=subnet_id, MapPublicIpOnLaunch={"Value": value}
    )
    return {}


def _subnet_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    now = _subnet_snapshot(read, p)["map_public_ip_on_launch"]
    return now == (p["value"] == "enable"), f"{p['subnet_id']} MapPublicIpOnLaunch={now}"


register(
    ActionSpec(
        name="subnet_set_auto_public_ip",
        group="Subnet / instance",
        label="Set subnet auto-assign public IP",
        description="Turn the subnet setting 'auto-assign public IPv4 address' on (enable) or "
        "off (disable). Affects only instances launched AFTER the change; an existing instance "
        "without a public IP needs eip_allocate_and_associate.",
        input_schema={
            "type": "object",
            "properties": {
                "subnet_id": {"type": "string", "pattern": "^subnet-[0-9a-f]+$"},
                "value": {"type": "string", "enum": ["enable", "disable"]},
            },
            "required": ["subnet_id", "value"],
            "additionalProperties": False,
        },
        write_actions=["ec2:ModifySubnetAttribute"],
        snapshot=_subnet_snapshot,
        precheck=lambda p, s: (
            f"{p['subnet_id']} already has auto-assign public IP "
            f"{'on' if s['map_public_ip_on_launch'] else 'off'}"
            if s["map_public_ip_on_launch"] == (p["value"] == "enable")
            else None
        ),
        preview=lambda p, s: preview(
            f"Turn auto-assign public IPv4 {'on' if p['value'] == 'enable' else 'off'} for "
            f"{p['subnet_id']}",
            [
                {
                    "field": f"Auto-assign public IPv4 of {p['subnet_id']}",
                    "before": "on" if s["map_public_ip_on_launch"] else "off",
                    "after": "on" if p["value"] == "enable" else "off",
                }
            ],
            "Only instances launched in the subnet after the change are affected; running "
            "instances keep their current addresses.",
            "low",
            "Set the subnet setting back to its previous value",
            f"{p['subnet_id']} has the new setting.",
        ),
        execute=lambda read, write, p, s: _set_subnet(
            write, p["subnet_id"], p["value"] == "enable"
        ),
        verify=_subnet_verify,
        undo=lambda read, write, p, s, r: _set_subnet(
            write, p["subnet_id"], s["map_public_ip_on_launch"]
        ),
        undo_description=lambda p, s: (
            f"Set auto-assign public IPv4 back to {'on' if s['map_public_ip_on_launch'] else 'off'}"
        ),
        # ModifySubnetAttribute has no DryRun parameter
    )
)


# ---- instance: start ---------------------------------------------------------------------


def _start_snapshot(read: Session, p: dict) -> dict:
    inst = instance(read, p["instance_id"])
    return {
        "instance_id": p["instance_id"],
        "state": inst["State"]["Name"],
        "_public_ip": inst.get("PublicIpAddress"),
        "_elastic_ips": elastic_ips_of(read, p["instance_id"]),
    }


def _start_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    def check() -> tuple[bool, str]:
        inst = instance(read, p["instance_id"])
        state = inst["State"]["Name"]
        return state == "running", f"{p['instance_id']} is {state}, public IP " + str(
            inst.get("PublicIpAddress")
        )

    return wait_until(check)


def _start(write: Session, p: dict, dry: bool = False) -> dict:
    fn = write.client("ec2").start_instances
    if dry:
        expect_dry_run(fn, InstanceIds=[p["instance_id"]])
    else:
        fn(InstanceIds=[p["instance_id"]])
    return {}


register(
    ActionSpec(
        name="instance_start",
        group="Subnet / instance",
        label="Start instance",
        description="Start a STOPPED instance. Without an Elastic IP its public IP changes; "
        "DNS records pointing to the old IP need dns_upsert_record. There is no automatic "
        "undo: AutoAWS never stops instances.",
        input_schema={
            "type": "object",
            "properties": {"instance_id": _INSTANCE_ID},
            "required": ["instance_id"],
            "additionalProperties": False,
        },
        write_actions=["ec2:StartInstances"],
        snapshot=_start_snapshot,
        precheck=lambda p, s: (
            None if s["state"] == "stopped" else f"{p['instance_id']} is {s['state']}, not stopped"
        ),
        preview=lambda p, s: preview(
            f"Start instance {p['instance_id']}",
            [{"field": f"State of {p['instance_id']}", "before": s["state"], "after": "running"}],
            "The instance boots and is billed while running. "
            + (
                f"It keeps its Elastic IP {s['_elastic_ips'][0]}."
                if s["_elastic_ips"]
                else "It gets a NEW public IP (it has no Elastic IP)."
            ),
            "low",
            "No automatic undo: stop the instance yourself if needed (AutoAWS never stops "
            "instances)",
            f"{p['instance_id']} is running.",
        ),
        execute=lambda read, write, p, s: _start(write, p),
        verify=_start_verify,
        undo=None,
        dry_run=lambda read, write, p, s: _start(write, p, dry=True),
    )
)


# ---- instance: security groups ---------------------------------------------------------


def _groups_snapshot(read: Session, p: dict) -> dict:
    inst = instance(read, p["instance_id"])
    group = read.client("ec2").describe_security_groups(GroupIds=[p["group_id"]])["SecurityGroups"][
        0
    ]
    return {
        "instance_id": p["instance_id"],
        "vpc_id": inst.get("VpcId"),
        "groups": sorted(g["GroupId"] for g in inst.get("SecurityGroups", [])),
        "network_interfaces": len(inst.get("NetworkInterfaces", [])),
        "group_vpc_id": group.get("VpcId"),
    }


def _attach_precheck(p: dict, s: dict) -> str | None:
    if s["network_interfaces"] > 1:
        return f"{p['instance_id']} has several network interfaces; change the interface instead"
    if s["group_vpc_id"] != s["vpc_id"]:
        return f"{p['group_id']} is in {s['group_vpc_id']}, not in the instance's VPC"
    if p["group_id"] in s["groups"]:
        return f"{p['instance_id']} already uses {p['group_id']}"
    if len(s["groups"]) >= 5:
        return f"{p['instance_id']} already has 5 security groups"
    return None


def _detach_precheck(p: dict, s: dict) -> str | None:
    if s["network_interfaces"] > 1:
        return f"{p['instance_id']} has several network interfaces; change the interface instead"
    if p["group_id"] not in s["groups"]:
        return f"{p['instance_id']} does not use {p['group_id']}"
    if len(s["groups"]) == 1:
        return f"{p['group_id']} is the only security group of {p['instance_id']}"
    return None


def _target_groups(p: dict, s: dict, attach: bool) -> list[str]:
    if attach:
        return sorted([*s["groups"], p["group_id"]])
    return [g for g in s["groups"] if g != p["group_id"]]


def _set_groups(write: Session, instance_id: str, groups: list[str], dry: bool = False) -> dict:
    fn = write.client("ec2").modify_instance_attribute
    if dry:
        expect_dry_run(fn, InstanceId=instance_id, Groups=groups)
    else:
        fn(InstanceId=instance_id, Groups=groups)
    return {}


def _groups_verify(attach: bool):
    def verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
        now = sorted(
            g["GroupId"] for g in instance(read, p["instance_id"]).get("SecurityGroups", [])
        )
        return now == _target_groups(p, s, attach), f"{p['instance_id']} groups: {', '.join(now)}"

    return verify


def _groups_spec(attach: bool) -> ActionSpec:
    verb = "attach" if attach else "detach"
    return ActionSpec(
        name=f"instance_{verb}_security_group",
        group="Subnet / instance",
        label=f"{verb.capitalize()} security group",
        description=(
            "Add one more security group (same VPC, max 5) to an instance, e.g. a group "
            "that already allows the needed port."
            if attach
            else "Remove one security group from an instance (never its last one), e.g. a "
            "group that opens a port it should not."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "instance_id": _INSTANCE_ID,
                "group_id": {"type": "string", "pattern": "^sg-[0-9a-f]+$"},
            },
            "required": ["instance_id", "group_id"],
            "additionalProperties": False,
        },
        write_actions=["ec2:ModifyInstanceAttribute"],
        snapshot=_groups_snapshot,
        precheck=_attach_precheck if attach else _detach_precheck,
        preview=lambda p, s: preview(
            f"{verb.capitalize()} {p['group_id']} {'to' if attach else 'from'} {p['instance_id']}",
            [
                {
                    "field": f"Security groups of {p['instance_id']}",
                    "before": ", ".join(s["groups"]),
                    "after": ", ".join(_target_groups(p, s, attach)),
                }
            ],
            f"The rules of {p['group_id']} {'now apply' if attach else 'no longer apply'} to "
            f"{p['instance_id']}.",
            "low" if attach else "medium",
            f"Set the security groups back to {', '.join(s['groups'])}",
            f"{p['instance_id']} uses {', '.join(_target_groups(p, s, attach))}.",
        ),
        execute=lambda read, write, p, s: _set_groups(
            write, p["instance_id"], _target_groups(p, s, attach)
        ),
        verify=_groups_verify(attach),
        undo=lambda read, write, p, s, r: _set_groups(write, p["instance_id"], s["groups"]),
        undo_description=lambda p, s: f"Set the security groups back to {', '.join(s['groups'])}",
        dry_run=lambda read, write, p, s: _set_groups(
            write, p["instance_id"], _target_groups(p, s, attach), dry=True
        ),
    )


register(_groups_spec(attach=True))
register(_groups_spec(attach=False))


# ---- Elastic IP ---------------------------------------------------------------------------


def _eip_snapshot(read: Session, p: dict) -> dict:
    inst = instance(read, p["instance_id"])
    snap = {
        "instance_id": p["instance_id"],
        "state": inst["State"]["Name"],
        "elastic_ips": elastic_ips_of(read, p["instance_id"]),
        # a dynamic public IP changes on its own (stop/start, EIP release): display only
        "_public_ip": inst.get("PublicIpAddress"),
    }
    if p.get("allocation_id"):
        address = read.client("ec2").describe_addresses(AllocationIds=[p["allocation_id"]])[
            "Addresses"
        ][0]
        snap["address"] = {
            "public_ip": address["PublicIp"],
            "association_id": address.get("AssociationId"),
        }
    return snap


def _eip_precheck(p: dict, s: dict) -> str | None:
    if s["state"] != "running":
        return f"{p['instance_id']} is {s['state']}, not running"
    if s["elastic_ips"]:
        return f"{p['instance_id']} already has Elastic IP {s['elastic_ips'][0]}"
    if s.get("address", {}).get("association_id"):
        return f"{s['address']['public_ip']} is already associated with another resource"
    return None


def _eip_new_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
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


def _eip_existing_execute(read: Session, write: Session, p: dict, s: dict) -> dict:
    assoc = write.client("ec2").associate_address(
        AllocationId=p["allocation_id"], InstanceId=p["instance_id"]
    )
    return {"association_id": assoc["AssociationId"], "public_ip": s["address"]["public_ip"]}


def _eip_verify(read: Session, p: dict, s: dict, r: dict) -> tuple[bool, str]:
    ip = instance(read, p["instance_id"]).get("PublicIpAddress")
    return ip == r["public_ip"], f"{p['instance_id']} public IP {ip}, Elastic IP {r['public_ip']}"


def _eip_new_undo(read: Session, write: Session, p: dict, s: dict, r: dict) -> None:
    ec2 = write.client("ec2")
    ec2.disassociate_address(AssociationId=r["association_id"])
    ec2.release_address(AllocationId=r["allocation_id"])


def _eip_preview(p: dict, s: dict) -> dict:
    existing = s.get("address", {}).get("public_ip")
    return preview(
        f"Attach {existing or 'a new Elastic IP'} to {p['instance_id']}",
        [
            {
                "field": f"Public IP of {p['instance_id']}",
                "before": f"{s['_public_ip'] or 'none'} (changes on every stop/start)",
                "after": f"{existing or 'a new Elastic IP'} (stays the same across stop/start)",
            }
        ],
        "The instance's public IP changes now to the Elastic IP; update DNS records that point "
        "to the old IP (dns_upsert_record with instance_id does it). An Elastic IP is billed "
        "like any public IPv4, also while unattached.",
        "low",
        "Detach the Elastic IP" + ("" if existing else " and release it"),
        f"The public IP of {p['instance_id']} equals the Elastic IP.",
    )


register(
    ActionSpec(
        name="eip_allocate_and_associate",
        group="Elastic IP",
        label="Attach new Elastic IP",
        description="Allocate a NEW Elastic IP and attach it to a running instance that has "
        "none, so it gets a public IP at all or keeps it across stop/start.",
        input_schema={
            "type": "object",
            "properties": {"instance_id": _INSTANCE_ID},
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
        execute=_eip_new_execute,
        verify=_eip_verify,
        undo=_eip_new_undo,
        undo_description=lambda p, s: "Detach and release the Elastic IP",
        # AssociateAddress needs a real allocation id: only the allocation can be dry-run
        dry_run=lambda read, write, p, s: expect_dry_run(
            write.client("ec2").allocate_address, Domain="vpc"
        ),
    )
)

register(
    ActionSpec(
        name="eip_associate",
        group="Elastic IP",
        label="Attach existing Elastic IP",
        description="Attach an Elastic IP the account already has and that is not attached "
        "(allocation_id eipalloc-...) to a running instance without one, e.g. the address a "
        "DNS record still points to.",
        input_schema={
            "type": "object",
            "properties": {
                "allocation_id": {"type": "string", "pattern": "^eipalloc-[0-9a-f]+$"},
                "instance_id": _INSTANCE_ID,
            },
            "required": ["allocation_id", "instance_id"],
            "additionalProperties": False,
        },
        write_actions=["ec2:AssociateAddress", "ec2:DisassociateAddress"],
        snapshot=_eip_snapshot,
        precheck=_eip_precheck,
        preview=_eip_preview,
        execute=_eip_existing_execute,
        verify=_eip_verify,
        undo=lambda read, write, p, s, r: write.client("ec2").disassociate_address(
            AssociationId=r["association_id"]
        ),
        undo_description=lambda p, s: "Detach the Elastic IP (it stays in the account)",
        dry_run=lambda read, write, p, s: expect_dry_run(
            write.client("ec2").associate_address,
            AllocationId=p["allocation_id"],
            InstanceId=p["instance_id"],
        ),
    )
)
