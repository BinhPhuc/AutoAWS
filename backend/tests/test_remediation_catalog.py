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


def test_catalogue_has_the_six_report_actions():
    assert set(CATALOG) == {
        "associate_route_table",
        "create_route_to_igw",
        "authorize_sg_ingress",
        "allocate_and_associate_eip",
        "upsert_a_record",
        "modify_health_check_path",
    }
    for spec in CATALOG.values():
        for action in spec.write_actions:
            assert not action.startswith(("iam:", "organizations:")), action
            assert action not in ("ec2:TerminateInstances", "ec2:StopInstances")


def test_associate_route_table(aws):
    n = _network(aws)
    out = _round_trip(
        "associate_route_table", {"subnet_id": n["subnet"], "route_table_id": n["public"]}
    )
    preview = out["prepared"].preview
    assert n["private"] in preview["changes"][0]["before"]
    assert n["public"] in preview["changes"][0]["after"]
    # pre-check: the target must have an Internet route and be another table
    _, error = prepare(
        aws, "associate_route_table", {"subnet_id": n["subnet"], "route_table_id": n["private"]}
    )
    assert "no active 0.0.0.0/0" in error


def test_create_route_to_igw(aws):
    n = _network(aws)
    out = _round_trip("create_route_to_igw", {"route_table_id": n["private"]})
    assert out["result"]["gateway_id"] == n["igw"]
    _, error = prepare(aws, "create_route_to_igw", {"route_table_id": n["public"]})
    assert "already has a 0.0.0.0/0 route" in error


def test_authorize_sg_ingress(aws):
    n = _network(aws)
    _round_trip("authorize_sg_ingress", {"group_id": n["sg"], "port": 8080, "cidr": "0.0.0.0/0"})
    for cidr in ("0.0.0.0/0", "::/0"):
        _, error = prepare(
            aws, "authorize_sg_ingress", {"group_id": n["sg"], "port": 22, "cidr": cidr}
        )
        assert "never opened to the whole Internet" in error
    prepared, error = prepare(
        aws, "authorize_sg_ingress", {"group_id": n["sg"], "port": 22, "cidr": "203.0.113.7/32"}
    )
    assert prepared and not error


def test_allocate_and_associate_eip(aws):
    n = _network(aws)
    out = _round_trip("allocate_and_associate_eip", {"instance_id": n["instance"]})
    assert out["result"]["public_ip"]
    # the Elastic IP was released by the undo: nothing left behind
    assert aws.client("ec2").describe_addresses()["Addresses"] == []


def test_upsert_a_record(aws):
    n = _network(aws)
    ip = aws.client("ec2").describe_instances(InstanceIds=[n["instance"]])["Reservations"][0][
        "Instances"
    ][0]["PublicIpAddress"]
    r53 = aws.client("route53")
    zone = r53.create_hosted_zone(Name="example.com.", CallerReference="z")["HostedZone"]["Id"]
    r53.change_resource_record_sets(
        HostedZoneId=zone,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": "app.example.com.",
                        "Type": "A",
                        "TTL": 300,
                        "ResourceRecords": [{"Value": "13.212.10.20"}],
                    },
                }
            ]
        },
    )
    out = _round_trip(
        "upsert_a_record", {"record_name": "app.example.com", "instance_id": n["instance"]}
    )
    assert out["result"]["value"] == ip
    _, error = prepare(aws, "upsert_a_record", {"record_name": "app.example.com", "ip": "8.8.8.8"})
    assert "not a public IP" in error
    _, error = prepare(aws, "upsert_a_record", {"record_name": "new.example.com", "ip": ip})
    assert "no A record" in error


def test_modify_health_check_path(aws):
    n = _network(aws)
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
    out = _round_trip("modify_health_check_path", {"target_group": "web-tg", "path": "/api/health"})
    assert out["result"]["previous_path"] == "/health"
    _, error = prepare(
        aws, "modify_health_check_path", {"target_group": "web-tg", "path": "health"}
    )
    assert "must start with /" in error


def test_unknown_action_and_bad_params(aws):
    assert "Unknown remediation action" in prepare(aws, "delete_vpc", {})[1]
    assert "Invalid parameters" in prepare(aws, "associate_route_table", {"subnet_id": "x"})[1]


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
