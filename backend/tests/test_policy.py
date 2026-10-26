"""The IAM policy we hand to users must cover every AWS call the code really makes.

moto does not enforce IAM, so a missing action (e.g. the ec2:DescribeRegions that
verify_session needs) only shows up on real AWS. These tests record the operations each
tool / verify actually calls and compare them with the declared actions and the policy.
"""

import boto3
import pytest

from app.aws.cloudformation import policy_actions, render_template
from app.aws.credentials import ReadOnlyViolation, guard_read_only, verify_session
from app.aws.registry import iam_action, is_read_only_action, list_tools, run_tool, tool
from tests.conftest import FAKE_KEY, FAKE_SECRET, REGION


def _recording_session() -> tuple[boto3.Session, set[str]]:
    session = boto3.Session(
        aws_access_key_id=FAKE_KEY, aws_secret_access_key=FAKE_SECRET, region_name=REGION
    )
    called: set[str] = set()

    def record(model, **_):
        called.add(iam_action(model.service_model.service_name, model.name))

    session.events.register("before-call", record)
    return session, called


@pytest.fixture
def world(aws):
    """Resources that drive every code path of the read tools (incl. fallbacks)."""
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(
        VpcId=vpc, CidrBlock="10.0.1.0/24", AvailabilityZone="ap-southeast-1a"
    )["Subnet"]["SubnetId"]
    subnet2 = ec2.create_subnet(
        VpcId=vpc, CidrBlock="10.0.2.0/24", AvailabilityZone="ap-southeast-1b"
    )["Subnet"]["SubnetId"]
    igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
    inst = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)[
        "Instances"
    ][0]["InstanceId"]

    r53 = aws.client("route53")
    zone = r53.create_hosted_zone(Name="example.com.", CallerReference="w")["HostedZone"]["Id"]

    elb = aws.client("elbv2")
    lb = elb.create_load_balancer(Name="web-alb", Subnets=[subnet, subnet2])["LoadBalancers"][0]
    tg = elb.create_target_group(Name="web-tg", Protocol="HTTP", Port=80, VpcId=vpc)[
        "TargetGroups"
    ][0]
    elb.create_listener(
        LoadBalancerArn=lb["LoadBalancerArn"],
        Protocol="HTTP",
        Port=80,
        DefaultActions=[{"Type": "forward", "TargetGroupArn": tg["TargetGroupArn"]}],
    )
    elb.register_targets(TargetGroupArn=tg["TargetGroupArn"], Targets=[{"Id": inst}])
    return {"vpc": vpc, "subnet": subnet, "subnet2": subnet2, "instance": inst, "zone": zone}


# Params that make each tool walk its widest code path (fallbacks, nested lookups).
def _params(name: str, w: dict) -> dict:
    return {
        "describe_instances": {"instance_ids": [w["instance"]]},
        "describe_instance_status": {"instance_ids": [w["instance"]]},
        "describe_route_tables": {"subnet_ids": [w["subnet"], w["subnet2"]]},
        "describe_network_acls": {"subnet_ids": [w["subnet"]]},
        "route53_list_records": {"domain": "app.example.com"},
    }.get(name, {})


# moto lacks a few read APIs; those tools are covered by stubbed tests in test_tools.py.
_MOTO_UNSUPPORTED = {"ssm_describe_instance_information"}


def test_every_call_a_tool_makes_is_declared_and_in_the_policy(world):
    allowed = set(policy_actions())
    checked = 0
    for spec in list_tools():
        if spec.stub or not spec.aws_actions or spec.name in _MOTO_UNSUPPORTED:
            continue
        session, called = _recording_session()
        result = run_tool(session, spec.name, _params(spec.name, world))
        assert result.status == "ok", f"{spec.name}: {result.error}"
        assert called, f"{spec.name} made no AWS call"
        assert called <= set(spec.aws_actions), (
            f"{spec.name} undeclared: {called - set(spec.aws_actions)}"
        )
        assert called <= allowed, f"{spec.name} not in policy: {called - allowed}"
        checked += 1
    assert checked >= 10


def test_verify_calls_are_in_the_policy(aws):
    session, called = _recording_session()
    verify_session(session)
    assert called == {"sts:GetCallerIdentity", "ec2:DescribeRegions"}
    assert called <= set(policy_actions())
    assert "ec2:DescribeRegions" in render_template("111122223333", "autoaws-x")


def test_policy_only_contains_read_only_actions():
    for action in policy_actions():
        assert is_read_only_action(action), action


@pytest.mark.parametrize(
    ("action", "allowed"),
    [
        ("ec2:DescribeInstances", True),
        ("route53:ListHostedZones", True),
        ("cloudtrail:LookupEvents", True),
        ("logs:StartQuery", True),
        ("logs:GetQueryResults", True),
        ("ec2:TerminateInstances", False),
        ("ec2:RunInstances", False),
        ("ec2:CreateRoute", False),
        ("logs:StopQuery", False),
        ("secretsmanager:GetSecretValue", False),
        ("s3:GetObject", False),
        ("s3:GetObjectVersion", False),
        ("ssm:GetParameters", False),
        ("kms:Decrypt", False),
        ("not-an-action", False),
    ],
)
def test_is_read_only_action(action, allowed):
    assert is_read_only_action(action) is allowed


@pytest.mark.parametrize("action", ["ec2:TerminateInstances", "secretsmanager:GetSecretValue"])
def test_registry_rejects_tools_declaring_forbidden_actions(action):
    with pytest.raises(ValueError, match="non read-only"):

        @tool(
            name=f"bad_{action.replace(':', '_')}",
            group="compute",
            label="bad",
            description="bad",
            input_schema={"type": "object", "properties": {}},
            aws_actions=[action],
        )
        def _bad(session, params):  # pragma: no cover
            return {}


def test_guarded_session_blocks_writes_at_runtime(aws):
    session = guard_read_only(
        boto3.Session(
            aws_access_key_id=FAKE_KEY, aws_secret_access_key=FAKE_SECRET, region_name=REGION
        )
    )
    ec2 = session.client("ec2")
    assert ec2.describe_vpcs()["Vpcs"] is not None
    with pytest.raises(ReadOnlyViolation, match="ec2:CreateVpc"):
        ec2.create_vpc(CidrBlock="10.9.0.0/16")
    with pytest.raises(ReadOnlyViolation, match="secretsmanager:GetSecretValue"):
        session.client("secretsmanager").get_secret_value(SecretId="db")
    # A tool that tried to write would surface as an error result, never as a write.
    assert not aws.client("ec2").describe_vpcs(
        Filters=[{"Name": "cidr", "Values": ["10.9.0.0/16"]}]
    )["Vpcs"]
