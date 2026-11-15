"""Remediation details from report §2.7.2: DryRun before writing, and a local backend that
restarts mid-way never leaves a proposal stuck (or applies it twice)."""

import dataclasses
import json

import pytest

from app.agent.schemas import DiagnosisAnswer, ProposalRef
from app.aws.remediation import catalog
from app.remediation import service
from app.storage.models import Connection, Conversation


@pytest.fixture
def world(store, aws, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "remediation_allow_access_keys", True)
    monkeypatch.setattr(settings, "remediation_verify_timeout_seconds", 0)
    monkeypatch.setattr(settings, "aws_endpoint_url", "")
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
    public = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=public, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
    private = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.associate_route_table(RouteTableId=private, SubnetId=subnet)
    sg = ec2.create_security_group(GroupName="app", Description="app", VpcId=vpc)["GroupId"]
    conn = store.create_connection(
        Connection(
            name="c",
            type="access_key",
            region="ap-southeast-1",
            status="connected",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
    )
    conv = store.create_conversation(Conversation(connection_id=conn.id))

    def propose(action: str, params: dict) -> str:
        answer = DiagnosisAnswer(
            summary="s", proposals=[ProposalRef(action=action, params=params, reason="r")]
        )
        service.attach_proposals(store, conv, "msg_1", conn, aws, answer)
        ref = answer.proposals[0]
        assert ref.proposal_id, ref.error
        return ref.proposal_id

    def approve_and_run(pid: str) -> dict:
        service.decide(store, store.get_proposal(pid), "approve")
        service.execute_proposal(store, pid)
        p = store.get_proposal(pid)
        return {
            "status": p.status,
            "error": p.error,
            "notes": [h["note"] for h in json.loads(p.history_json)],
        }

    return {
        "store": store,
        "ec2": ec2,
        "settings": settings,
        "subnet": subnet,
        "public": public,
        "sg": sg,
        "propose": propose,
        "run": approve_and_run,
    }


def _inbound(ec2, sg) -> list:
    return ec2.describe_security_groups(GroupIds=[sg])["SecurityGroups"][0]["IpPermissions"]


def test_dry_run_passes_then_the_change_is_applied_once(world, monkeypatch):
    monkeypatch.setattr(world["settings"], "remediation_dry_run", True)
    pid = world["propose"](
        "sg_add_rule", {"group_id": world["sg"], "from_port": 8080, "cidr": "0.0.0.0/0"}
    )
    out = world["run"](pid)
    assert out["status"] == "SUCCEEDED", out
    assert "dry run passed" in out["notes"]
    assert len(_inbound(world["ec2"], world["sg"])) == 1  # the dry run wrote nothing


def test_dry_run_refused_means_nothing_is_written(world, monkeypatch):
    monkeypatch.setattr(world["settings"], "remediation_dry_run", True)
    spec = catalog.CATALOG["sg_add_rule"]

    def denied(*_):
        raise catalog.DryRunDenied("You are not authorized to perform this operation.")

    monkeypatch.setitem(catalog.CATALOG, spec.name, dataclasses.replace(spec, dry_run=denied))
    pid = world["propose"](
        "sg_add_rule", {"group_id": world["sg"], "from_port": 8080, "cidr": "0.0.0.0/0"}
    )
    out = world["run"](pid)
    assert out["status"] == "FAILED" and out["error"].startswith("Permission:")
    assert _inbound(world["ec2"], world["sg"]) == []


def test_an_endpoint_that_ignores_dry_run_stops_the_execution(world, monkeypatch):
    """moto (and LocalStack) apply ReplaceRouteTableAssociation even with DryRun=True:
    AutoAWS must notice the missing DryRunOperation answer and stop."""
    monkeypatch.setattr(world["settings"], "remediation_dry_run", True)
    pid = world["propose"](
        "route_table_associate", {"subnet_id": world["subnet"], "route_table_id": world["public"]}
    )
    out = world["run"](pid)
    assert out["status"] == "FAILED" and "ignored DryRun" in out["error"]


def test_dry_run_is_off_against_emulators(world, monkeypatch):
    monkeypatch.setattr(world["settings"], "remediation_dry_run", True)
    monkeypatch.setattr(world["settings"], "aws_endpoint_url", "http://localhost:4566")
    assert world["settings"].dry_run_enabled is False
    monkeypatch.setattr(world["settings"], "aws_endpoint_url", "")
    assert world["settings"].dry_run_enabled is True


def test_restart_recovers_or_closes_interrupted_proposals(world):
    store = world["store"]
    rt = {"subnet_id": world["subnet"], "route_table_id": world["public"]}
    sg8080 = {"group_id": world["sg"], "from_port": 8080, "cidr": "0.0.0.0/0"}
    sg443 = {"group_id": world["sg"], "from_port": 443, "cidr": "0.0.0.0/0"}

    approved = world["propose"]("route_table_associate", rt)  # approved, never started
    service.decide(store, store.get_proposal(approved), "approve")

    applied = world["propose"]("sg_add_rule", sg8080)  # written, not verified yet
    service.decide(store, store.get_proposal(applied), "approve")
    service.recheck_step(store, applied)
    service.execute_step(store, applied)

    unknown = world["propose"]("sg_add_rule", sg443)  # died before storing a result
    service.decide(store, store.get_proposal(unknown), "approve")
    service.recheck_step(store, unknown)

    handled = service.recover_interrupted(store)
    assert set(handled) == {approved, applied, unknown}
    assert store.get_proposal(approved).status == "SUCCEEDED"
    assert store.get_proposal(applied).status == "SUCCEEDED"
    closed = store.get_proposal(unknown)
    assert closed.status == "FAILED" and closed.error.startswith("Interrupted")
    # 8080 applied exactly once, 443 never retried blindly
    ports = sorted(p["FromPort"] for p in _inbound(world["ec2"], world["sg"]))
    assert ports == [8080]
    assert service.recover_interrupted(store) == []  # idempotent
