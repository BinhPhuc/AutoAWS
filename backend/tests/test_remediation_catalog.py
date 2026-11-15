"""Remediation catalogue on moto: pre-check, execute, verify, undo for every action, and the
calls each action makes stay inside its declared write actions / the read-only policy."""

import boto3
import pytest

from app.aws.cloudformation import policy_actions
from app.aws.registry import iam_action
from app.aws.remediation.catalog import CATALOG, get_action
from app.aws.remediation.sessions import (
    RemediationDisabled,
    RemediationViolation,
    remediation_session,
)
from app.remediation.service import prepare, snapshot_hash
from app.storage.models import Connection
from tests.conftest import FAKE_KEY, FAKE_SECRET, REGION


@pytest.fixture(autouse=True)
def fast_verify(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "remediation_verify_timeout_seconds", 0)
    monkeypatch.setattr(get_settings(), "remediation_verify_poll_seconds", 0)


def _recording(called: set[str]) -> boto3.Session:
    session = boto3.Session(
        aws_access_key_id=FAKE_KEY, aws_secret_access_key=FAKE_SECRET, region_name=REGION
    )
    session.events.register(
        "before-call",
        lambda model, **_: called.add(iam_action(model.service_model.service_name, model.name)),
    )
    return session


def _network(aws):
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    ec2.modify_subnet_attribute(SubnetId=subnet, MapPublicIpOnLaunch={"Value": True})
    igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
    public = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=public, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
    private = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.associate_route_table(RouteTableId=private, SubnetId=subnet)  # the KB1 incident
    inst = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)[
        "Instances"
    ][0]["InstanceId"]
    sg = ec2.create_security_group(GroupName="app", Description="app", VpcId=vpc)["GroupId"]
    return {
        "ec2": ec2,
        "vpc": vpc,
        "subnet": subnet,
        "igw": igw,
        "public": public,
        "private": private,
        "instance": inst,
        "sg": sg,
    }


def _round_trip(action: str, params: dict) -> dict:
    """prepare -> execute -> verify -> undo, recording every AWS call."""
    reads: set[str] = set()
    writes: set[str] = set()
    read, write = _recording(reads), _recording(writes)
    prepared, error = prepare(read, action, params)
    assert prepared, error
    spec = get_action(action)
    result = spec.execute(read, write, params, prepared.snapshot)
    ok, details = spec.verify(read, params, prepared.snapshot, result)
    assert ok, details
    spec.undo(read, write, params, prepared.snapshot, result)
    restored = spec.snapshot(read, params)
    assert snapshot_hash(restored) == snapshot_hash(prepared.snapshot), (
        restored,
        prepared.snapshot,
    )
    # writes only through the declared actions, reads only what the read-only role grants
    assert writes <= set(spec.write_actions), writes - set(spec.write_actions)
    assert reads <= set(policy_actions()), reads - set(policy_actions())
    return {"prepared": prepared, "result": result, "writes": writes}


def _error(aws, action: str, params: dict) -> str:
    prepared, error = prepare(aws, action, params)
    assert prepared is None, f"{action} {params} should be refused"
    return error


def _zone(aws) -> str:
    return aws.client("route53").create_hosted_zone(Name="example.com.", CallerReference="z")[
        "HostedZone"
    ]["Id"]


def _record(aws, zone: str, name: str, rtype: str, value: str) -> None:
    aws.client("route53").change_resource_record_sets(
        HostedZoneId=zone,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": name,
                        "Type": rtype,
                        "TTL": 300,
                        "ResourceRecords": [{"Value": value}],
                    },
                }
            ]
        },
    )


def _load_balancer(aws, n: dict) -> dict:
    ec2 = n["ec2"]
    subnet2 = ec2.create_subnet(
        VpcId=n["vpc"], CidrBlock="10.0.2.0/24", AvailabilityZone=f"{REGION}b"
    )["Subnet"]["SubnetId"]
    elb = aws.client("elbv2")
    lb = elb.create_load_balancer(Name="web", Subnets=[n["subnet"], subnet2])["LoadBalancers"][0]
    tg = elb.create_target_group(
        Name="web-tg", Protocol="HTTP", Port=80, VpcId=n["vpc"], HealthCheckPath="/health"
    )["TargetGroups"][0]
    elb.create_listener(
        LoadBalancerArn=lb["LoadBalancerArn"],
        Protocol="HTTP",
        Port=80,
        DefaultActions=[{"Type": "forward", "TargetGroupArn": tg["TargetGroupArn"]}],
    )
    elb.register_targets(TargetGroupArn=tg["TargetGroupArn"], Targets=[{"Id": n["instance"]}])
    return {"elb": elb, "lb": lb, "tg": tg}


def test_catalogue_is_generic_and_never_destructive():
    assert set(CATALOG) == {
        "sg_add_rule",
        "sg_remove_rule",
        "route_add",
        "route_replace",
        "route_delete",
        "route_table_associate",
        "nacl_add_entry",
        "nacl_replace_entry",
        "nacl_delete_entry",
        "nacl_associate",
        "subnet_set_auto_public_ip",
        "instance_start",
        "instance_attach_security_group",
        "instance_detach_security_group",
        "eip_allocate_and_associate",
        "eip_associate",
        "dns_upsert_record",
        "tg_modify_health_check",
        "tg_register_target",
        "tg_deregister_target",
    }
    from app.aws.cloudformation import REMEDIATION_DENIED

    for spec in CATALOG.values():
        assert spec.group and spec.label and spec.description
        for action in spec.write_actions:
            assert not action.startswith(("iam:", "organizations:")), action
            assert action not in REMEDIATION_DENIED, (spec.name, action)
    # only starting an instance has no automatic undo (stopping is never allowed)
    assert [n for n, spec in CATALOG.items() if spec.undo is None] == ["instance_start"]


# ---- security groups -----------------------------------------------------------------


def test_sg_add_and_remove_rules(aws):
    n = _network(aws)
    web = {"group_id": n["sg"], "from_port": 8080, "cidr": "0.0.0.0/0"}
    out = _round_trip("sg_add_rule", web)
    assert "ingress tcp/8080 from 0.0.0.0/0" in out["prepared"].preview["summary"]
    _round_trip("sg_add_rule", {**web, "protocol": "udp", "from_port": 5000, "to_port": 5010})
    _round_trip("sg_add_rule", {**web, "direction": "egress", "from_port": 443})
    other = n["ec2"].create_security_group(GroupName="lb", Description="lb", VpcId=n["vpc"])
    _round_trip(
        "sg_add_rule",
        {"group_id": n["sg"], "from_port": 80, "source_group_id": other["GroupId"]},
    )
    _round_trip("sg_add_rule", {"group_id": n["sg"], "protocol": "icmp", "cidr": "10.0.0.0/8"})

    # remove an existing rule (and put it back on undo, description included)
    n["ec2"].authorize_security_group_ingress(
        GroupId=n["sg"],
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "temp"}],
            }
        ],
    )
    _round_trip("sg_remove_rule", {"group_id": n["sg"], "from_port": 22, "cidr": "0.0.0.0/0"})
    # the default egress rule (all traffic) can be removed too
    _round_trip(
        "sg_remove_rule",
        {"group_id": n["sg"], "direction": "egress", "protocol": "all", "cidr": "0.0.0.0/0"},
    )


def test_sg_rules_refused(aws):
    n = _network(aws)
    sg = n["sg"]
    for params in (
        {"group_id": sg, "from_port": 22, "cidr": "0.0.0.0/0"},
        {"group_id": sg, "from_port": 3389, "cidr": "::/0"},
        {"group_id": sg, "from_port": 1, "to_port": 1024, "cidr": "0.0.0.0/0"},
        {"group_id": sg, "protocol": "all", "cidr": "0.0.0.0/0"},
    ):
        assert "never opened to the whole Internet" in _error(aws, "sg_add_rule", params)
    # the user's own IP is fine; outbound 22 to anywhere too
    assert prepare(aws, "sg_add_rule", {"group_id": sg, "from_port": 22, "cidr": "203.0.113.7/32"})[
        0
    ]
    assert prepare(
        aws,
        "sg_add_rule",
        {"group_id": sg, "direction": "egress", "from_port": 22, "cidr": "0.0.0.0/0"},
    )[0]
    assert "exactly one of cidr" in _error(aws, "sg_add_rule", {"group_id": sg, "from_port": 80})
    assert "from_port is required" in _error(
        aws, "sg_add_rule", {"group_id": sg, "cidr": "1.2.3.4/32"}
    )
    assert "not a valid CIDR" in _error(
        aws, "sg_add_rule", {"group_id": sg, "from_port": 80, "cidr": "x"}
    )
    assert "has no rule" in _error(
        aws, "sg_remove_rule", {"group_id": sg, "from_port": 8443, "cidr": "0.0.0.0/0"}
    )


# ---- routes --------------------------------------------------------------------------


def test_routes_add_replace_delete(aws):
    n = _network(aws)
    ec2 = n["ec2"]
    igw = {"target_type": "internet_gateway", "target_id": n["igw"]}
    _round_trip(
        "route_add", {"route_table_id": n["private"], "destination_cidr": "0.0.0.0/0", **igw}
    )
    eip = ec2.allocate_address(Domain="vpc")["AllocationId"]
    nat = ec2.create_nat_gateway(SubnetId=n["subnet"], AllocationId=eip)["NatGateway"][
        "NatGatewayId"
    ]
    _round_trip(
        "route_replace",
        {
            "route_table_id": n["public"],
            "destination_cidr": "0.0.0.0/0",
            "target_type": "nat_gateway",
            "target_id": nat,
        },
    )
    _round_trip("route_delete", {"route_table_id": n["public"], "destination_cidr": "0.0.0.0/0"})


def test_routes_refused(aws):
    n = _network(aws)
    igw = {"target_type": "internet_gateway", "target_id": n["igw"]}
    assert "use route_replace" in _error(
        aws, "route_add", {"route_table_id": n["public"], "destination_cidr": "0.0.0.0/0", **igw}
    )
    assert "use route_add" in _error(
        aws,
        "route_replace",
        {"route_table_id": n["private"], "destination_cidr": "0.0.0.0/0", **igw},
    )
    local = {"route_table_id": n["public"], "destination_cidr": "10.0.0.0/16"}
    assert "local route cannot be deleted" in _error(aws, "route_delete", local)
    assert "local route cannot be changed" in _error(aws, "route_replace", {**local, **igw})
    other_vpc = n["ec2"].create_vpc(CidrBlock="10.9.0.0/16")["Vpc"]["VpcId"]
    other_igw = n["ec2"].create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    n["ec2"].attach_internet_gateway(InternetGatewayId=other_igw, VpcId=other_vpc)
    assert "is not attached to" in _error(
        aws,
        "route_add",
        {
            "route_table_id": n["private"],
            "destination_cidr": "0.0.0.0/0",
            "target_type": "internet_gateway",
            "target_id": other_igw,
        },
    )


def test_route_table_associate(aws):
    n = _network(aws)
    out = _round_trip(
        "route_table_associate", {"subnet_id": n["subnet"], "route_table_id": n["public"]}
    )
    preview = out["prepared"].preview
    assert n["private"] in preview["changes"][0]["before"]
    assert n["public"] in preview["changes"][0]["after"]
    assert "the subnet is public" in preview["impact"]
    assert "already uses" in _error(
        aws, "route_table_associate", {"subnet_id": n["subnet"], "route_table_id": n["private"]}
    )


# ---- network ACLs --------------------------------------------------------------------


def test_nacl_entries(aws):
    n = _network(aws)
    acl = n["ec2"].create_network_acl(VpcId=n["vpc"])["NetworkAcl"]["NetworkAclId"]
    entry = {
        "network_acl_id": acl,
        "rule_number": 100,
        "direction": "egress",
        "rule_action": "deny",
        "protocol": "tcp",
        "from_port": 1024,
        "to_port": 65535,
        "cidr": "0.0.0.0/0",
    }
    _round_trip("nacl_add_entry", entry)
    n["ec2"].create_network_acl_entry(
        NetworkAclId=acl,
        RuleNumber=100,
        Egress=True,
        RuleAction="deny",
        Protocol="6",
        PortRange={"From": 1024, "To": 65535},
        CidrBlock="0.0.0.0/0",
    )
    _round_trip("nacl_replace_entry", {**entry, "rule_action": "allow"})
    _round_trip(
        "nacl_delete_entry", {"network_acl_id": acl, "rule_number": 100, "direction": "egress"}
    )
    assert "use nacl_replace_entry" in _error(aws, "nacl_add_entry", entry)
    assert "already has these values" in _error(aws, "nacl_replace_entry", entry)
    ssh = {**entry, "rule_number": 90, "direction": "ingress", "rule_action": "allow"}
    assert "never opened" in _error(aws, "nacl_add_entry", {**ssh, "from_port": 22, "to_port": 22})
    assert prepare(
        aws, "nacl_add_entry", {**ssh, "rule_action": "deny", "from_port": 22, "to_port": 22}
    )[0]
    assert "Invalid parameters" in _error(
        aws, "nacl_delete_entry", {"network_acl_id": acl, "rule_number": 32767}
    )


def test_nacl_associate(aws):
    n = _network(aws)
    acl = n["ec2"].create_network_acl(VpcId=n["vpc"])["NetworkAcl"]["NetworkAclId"]
    _round_trip("nacl_associate", {"subnet_id": n["subnet"], "network_acl_id": acl})
    other = n["ec2"].create_vpc(CidrBlock="10.9.0.0/16")["Vpc"]["VpcId"]
    foreign = n["ec2"].create_network_acl(VpcId=other)["NetworkAcl"]["NetworkAclId"]
    assert "not in the subnet's VPC" in _error(
        aws, "nacl_associate", {"subnet_id": n["subnet"], "network_acl_id": foreign}
    )


# ---- subnet / instance -----------------------------------------------------------------


def test_subnet_auto_public_ip(aws):
    n = _network(aws)
    _round_trip("subnet_set_auto_public_ip", {"subnet_id": n["subnet"], "value": "disable"})
    assert "already has auto-assign" in _error(
        aws, "subnet_set_auto_public_ip", {"subnet_id": n["subnet"], "value": "enable"}
    )


def test_instance_start_has_no_undo(aws):
    n = _network(aws)
    params = {"instance_id": n["instance"]}
    assert "not stopped" in _error(aws, "instance_start", params)
    n["ec2"].stop_instances(InstanceIds=[n["instance"]])
    writes: set[str] = set()
    read, write = _recording(set()), _recording(writes)
    prepared, error = prepare(read, "instance_start", params)
    assert prepared, error
    assert "No automatic undo" in prepared.preview["rollback"]
    spec = get_action("instance_start")
    result = spec.execute(read, write, params, prepared.snapshot)
    assert spec.verify(read, params, prepared.snapshot, result)[0]
    assert writes == {"ec2:StartInstances"} and spec.undo is None


def test_instance_security_groups(aws):
    n = _network(aws)
    extra = n["ec2"].create_security_group(GroupName="x", Description="x", VpcId=n["vpc"])[
        "GroupId"
    ]
    _round_trip("instance_attach_security_group", {"instance_id": n["instance"], "group_id": extra})
    n["ec2"].modify_instance_attribute(InstanceId=n["instance"], Groups=[n["sg"], extra])
    _round_trip("instance_detach_security_group", {"instance_id": n["instance"], "group_id": extra})
    n["ec2"].modify_instance_attribute(InstanceId=n["instance"], Groups=[n["sg"]])
    assert "only security group" in _error(
        aws, "instance_detach_security_group", {"instance_id": n["instance"], "group_id": n["sg"]}
    )
    assert "already uses" in _error(
        aws, "instance_attach_security_group", {"instance_id": n["instance"], "group_id": n["sg"]}
    )


def test_elastic_ips(aws):
    n = _network(aws)
    out = _round_trip("eip_allocate_and_associate", {"instance_id": n["instance"]})
    assert out["result"]["public_ip"]
    # the Elastic IP AutoAWS allocated was released by the undo: nothing left behind
    assert aws.client("ec2").describe_addresses()["Addresses"] == []
    alloc = n["ec2"].allocate_address(Domain="vpc")["AllocationId"]
    _round_trip("eip_associate", {"allocation_id": alloc, "instance_id": n["instance"]})
    # an existing Elastic IP is only detached on undo, never released
    assert [a["AllocationId"] for a in n["ec2"].describe_addresses()["Addresses"]] == [alloc]


# ---- Route 53 --------------------------------------------------------------------------


def test_dns_records(aws):
    n = _network(aws)
    ip = n["ec2"].describe_instances(InstanceIds=[n["instance"]])["Reservations"][0]["Instances"][
        0
    ]["PublicIpAddress"]
    zone = _zone(aws)
    _record(aws, zone, "app.example.com.", "A", "13.212.10.20")
    out = _round_trip(
        "dns_upsert_record", {"record_name": "app.example.com", "instance_id": n["instance"]}
    )
    assert out["result"]["record"]["values"] == [ip]
    # a NEW record: the undo deletes what AutoAWS created
    _round_trip("dns_upsert_record", {"record_name": "ip.example.com", "value": ip})
    _round_trip(
        "dns_upsert_record",
        {"record_name": "_check.example.com", "type": "TXT", "value": "verify=abc"},
    )
    lb = _load_balancer(aws, n)["lb"]
    _round_trip(
        "dns_upsert_record",
        {"record_name": "www.example.com", "type": "CNAME", "value": lb["DNSName"]},
    )
    _round_trip("dns_upsert_record", {"record_name": "example.com", "load_balancer": "web"})
    assert (
        aws.client("route53").list_resource_record_sets(HostedZoneId=zone)["ResourceRecordSets"][
            -1
        ]["Name"]
        == "app.example.com."
    )


def test_dns_refused(aws):
    n = _network(aws)
    zone = _zone(aws)
    _record(aws, zone, "app.example.com.", "A", "13.212.10.20")
    dns = "dns_upsert_record"
    assert "not an address of an instance" in _error(
        aws, dns, {"record_name": "app.example.com", "value": "8.8.8.8"}
    )
    assert "neither an AWS endpoint" in _error(
        aws, dns, {"record_name": "www.example.com", "type": "CNAME", "value": "evil.attacker.tld"}
    )
    assert "zone apex" in _error(
        aws, dns, {"record_name": "example.com", "type": "CNAME", "value": "x.amazonaws.com"}
    )
    assert "a CNAME must be alone" in _error(
        aws, dns, {"record_name": "app.example.com", "type": "CNAME", "value": "x.amazonaws.com"}
    )
    assert "No hosted zone" in _error(
        aws, dns, {"record_name": "app.other.org", "instance_id": n["instance"]}
    )
    assert "exactly one of" in _error(
        aws,
        dns,
        {"record_name": "app.example.com", "value": "1.2.3.4", "instance_id": n["instance"]},
    )
    assert "only for A / AAAA" in _error(
        aws, dns, {"record_name": "t.example.com", "type": "TXT", "instance_id": n["instance"]}
    )


# ---- load balancer target groups ---------------------------------------------------------


def test_target_group_health_check(aws):
    n = _network(aws)
    _load_balancer(aws, n)
    out = _round_trip("tg_modify_health_check", {"target_group": "web-tg", "path": "/api/health"})
    assert out["result"]["changes"] == {"path": "/api/health"}
    _round_trip(
        "tg_modify_health_check",
        {
            "target_group": "web-tg",
            "interval_seconds": 10,
            "timeout_seconds": 5,
            "matcher": "200-399",
        },
    )
    assert "must start with /" in _error(
        aws, "tg_modify_health_check", {"target_group": "web-tg", "path": "health"}
    )
    assert "already has these" in _error(
        aws, "tg_modify_health_check", {"target_group": "web-tg", "path": "/health"}
    )
    assert "shorter than the interval" in _error(
        aws, "tg_modify_health_check", {"target_group": "web-tg", "timeout_seconds": 60}
    )


def test_target_group_targets(aws):
    n = _network(aws)
    _load_balancer(aws, n)
    _round_trip("tg_deregister_target", {"target_group": "web-tg", "target_id": n["instance"]})
    second = n["ec2"].run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=n["subnet"]
    )["Instances"][0]["InstanceId"]
    _round_trip("tg_register_target", {"target_group": "web-tg", "target_id": second})
    assert "already registered" in _error(
        aws, "tg_register_target", {"target_group": "web-tg", "target_id": n["instance"]}
    )
    assert "not registered" in _error(
        aws, "tg_deregister_target", {"target_group": "web-tg", "target_id": second}
    )


def test_unknown_action_and_bad_params(aws):
    assert "Unknown remediation action" in prepare(aws, "delete_vpc", {})[1]
    assert "Invalid parameters" in prepare(aws, "route_table_associate", {"subnet_id": "x"})[1]


# ---- the executor's write session ---------------------------------------------------------


def test_write_session_is_locked_to_the_action(aws, monkeypatch):
    from app.config import get_settings

    conn = Connection(
        name="lab",
        type="access_key",
        region=REGION,
        access_key_id=FAKE_KEY,
        secret_access_key=FAKE_SECRET,
    )
    with pytest.raises(RemediationDisabled):
        remediation_session(conn, ["ec2:CreateRoute"], "prop_x")

    monkeypatch.setattr(get_settings(), "remediation_allow_access_keys", True)
    n = _network(aws)
    session = remediation_session(conn, ["ec2:CreateRoute"], "prop_x")
    ec2 = session.client("ec2")
    with pytest.raises(RemediationViolation, match="ec2:TerminateInstances"):
        ec2.terminate_instances(InstanceIds=[n["instance"]])
    with pytest.raises(RemediationViolation, match="ec2:DescribeVpcs"):
        ec2.describe_vpcs()  # even reads: the write session does writes only
    ec2.create_route(
        RouteTableId=n["private"], DestinationCidrBlock="0.0.0.0/0", GatewayId=n["igw"]
    )
    state = aws.client("ec2").describe_instances(InstanceIds=[n["instance"]])
    assert state["Reservations"][0]["Instances"][0]["State"]["Name"] == "running"


def test_role_connection_without_remediation_role_cannot_write():
    conn = Connection(name="prod", type="role", region=REGION, role_arn="arn:aws:iam::1:role/R")
    with pytest.raises(RemediationDisabled):
        remediation_session(conn, ["ec2:CreateRoute"], "prop_x")
