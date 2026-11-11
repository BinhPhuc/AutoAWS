"""Human-in-the-loop flow end to end through the API (moto): the agent proposes, the server
pre-checks and stores, the user decides, the executor writes, re-checks and verifies."""

import dataclasses
from datetime import timedelta

import pytest

from app.agent.schemas import SUBMIT_TOOL_NAME
from app.aws.remediation import catalog
from app.llm.base import LLMResponse, ToolCallRequest
from app.storage.models import utcnow


@pytest.fixture(autouse=True)
def remediation_on(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "remediation_allow_access_keys", True)
    monkeypatch.setattr(settings, "remediation_verify_timeout_seconds", 0)
    monkeypatch.setattr(settings, "remediation_verify_poll_seconds", 0)


@pytest.fixture
def kb1(aws):
    """Subnet moved to a route table without Internet route (KB1)."""
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
    public = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=public, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
    private = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.associate_route_table(RouteTableId=private, SubnetId=subnet)
    sg = ec2.create_security_group(GroupName="web", Description="web", VpcId=vpc)["GroupId"]
    return {"ec2": ec2, "subnet": subnet, "public": public, "private": private, "sg": sg}


def _current_rt(ec2, subnet: str) -> str:
    rts = ec2.describe_route_tables(
        Filters=[{"Name": "association.subnet-id", "Values": [subnet]}]
    )["RouteTables"]
    return rts[0]["RouteTableId"] if rts else "main"


class ProposingProvider:
    """Answers at once with the given proposals."""

    name = "scripted"
    enforce_time_limit = True

    def __init__(self, proposals: list[dict]):
        self.proposals = proposals
        self.seen: list = []

    async def chat(self, messages, tools):
        self.seen.append(list(messages))
        answer = {
            "summary": "Subnet mất tuyến ra Internet.",
            "root_causes": [{"statement": "Thiếu 0.0.0.0/0", "confidence": "high", "evidence": []}],
            "fix_steps": ["Gắn lại route table public"],
            "unverified": [],
            "confidence": "high",
            "proposals": self.proposals,
        }
        call = ToolCallRequest(id="final", name=SUBMIT_TOOL_NAME, input=answer)
        return LLMResponse(tool_calls=[call], stop_reason="tool_use")


def _ask(
    client, connection, monkeypatch, proposals, conv_id=None
) -> tuple[str, dict, ProposingProvider]:
    from app import worker

    provider = ProposingProvider(proposals)
    monkeypatch.setattr(worker, "get_provider", lambda: provider)
    if conv_id is None:
        conv_id = client.post(
            "/api/conversations", json={"connection_id": connection["id"]}
        ).json()["data"]["id"]
    from tests.conftest import ask

    _, events = ask(client, conv_id, "Không SSH được")
    answer = next((d["answer"] for t, d in events if t == "answer"), None)
    return conv_id, answer, provider


def _fix(kb1) -> dict:
    return {
        "action": "associate_route_table",
        "params": {"subnet_id": kb1["subnet"], "route_table_id": kb1["public"]},
        "reason": "Gắn subnet về route table public",
    }


def _decide(client, proposal_id, decision, feedback=""):
    return client.post(
        f"/api/proposals/{proposal_id}/decision", json={"decision": decision, "feedback": feedback}
    ).json()


def test_approve_executes_and_verifies(client, connection, kb1, monkeypatch):
    conv_id, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    [ref] = answer["proposals"]
    assert ref["error"] is None and ref["proposal_id"].startswith("prop_")

    p = client.get(f"/api/proposals/{ref['proposal_id']}").json()["data"]
    assert p["status"] == "PENDING_APPROVAL" and p["conversation_id"] == conv_id
    assert kb1["private"] in p["preview"]["changes"][0]["before"]
    assert p["expires_at"]
    # nothing changed before the approval
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["private"]

    body = _decide(client, p["id"], "approve")
    assert body["message"] == "Proposal approved"
    p = client.get(f"/api/proposals/{p['id']}").json()["data"]
    assert p["status"] == "SUCCEEDED", p
    assert p["verification"]["ok"] is True
    assert [h["status"] for h in p["history"]] == [
        "PENDING_APPROVAL",
        "APPROVED",
        "EXECUTING",
        "SUCCEEDED",
    ]
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["public"]

    # a decided proposal cannot be decided again
    again = _decide(client, p["id"], "approve")
    assert again["status_code"] == 409 and again["error"] == "PROPOSAL_NOT_PENDING"

    listed = client.get(f"/api/proposals?conversation_id={conv_id}").json()["data"]
    assert [x["id"] for x in listed] == [p["id"]]


def test_reject_and_feedback_change_nothing(client, connection, kb1, monkeypatch):
    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pid = answer["proposals"][0]["proposal_id"]
    assert _decide(client, pid, "reject")["data"]["proposal"]["status"] == "REJECTED"

    conv_id, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pid = answer["proposals"][0]["proposal_id"]
    missing = _decide(client, pid, "feedback", "")
    assert missing["status_code"] == 422
    body = _decide(client, pid, "feedback", "chỉ sửa vào giờ thấp điểm")["data"]
    assert body["proposal"]["status"] == "SUPERSEDED"
    assert (
        "chỉ sửa vào giờ thấp điểm" in body["followup_question"]
        and pid in body["followup_question"]
    )
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["private"]

    # the next turn tells the model what happened to its proposals
    _, _, provider = _ask(client, connection, monkeypatch, [], conv_id=conv_id)
    question = provider.seen[0][-1].content
    assert f"{pid} fix associate_route_table" in question and "SUPERSEDED" in question


def test_resource_changed_since_the_preview_is_stale(client, connection, kb1, monkeypatch):
    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pid = answer["proposals"][0]["proposal_id"]
    # someone fixes it by hand in the meantime (to yet another table)
    ec2 = kb1["ec2"]
    other = ec2.create_route_table(
        VpcId=ec2.describe_subnets(SubnetIds=[kb1["subnet"]])["Subnets"][0]["VpcId"]
    )["RouteTable"]["RouteTableId"]
    assoc = ec2.describe_route_tables(RouteTableIds=[kb1["private"]])["RouteTables"][0][
        "Associations"
    ][0]
    ec2.replace_route_table_association(
        AssociationId=assoc["RouteTableAssociationId"], RouteTableId=other
    )

    _decide(client, pid, "approve")
    p = client.get(f"/api/proposals/{pid}").json()["data"]
    assert p["status"] == "STALE" and "changed" in p["error"]
    assert _current_rt(ec2, kb1["subnet"]) == other  # not overwritten


def test_failed_verification_proposes_a_rollback(client, connection, kb1, monkeypatch):
    spec = catalog.CATALOG["associate_route_table"]
    monkeypatch.setitem(
        catalog.CATALOG,
        "associate_route_table",
        dataclasses.replace(spec, verify=lambda *a: (False, "forced failure")),
    )
    conv_id, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pid = answer["proposals"][0]["proposal_id"]
    _decide(client, pid, "approve")
    p = client.get(f"/api/proposals/{pid}").json()["data"]
    assert p["status"] == "VERIFY_FAILED"
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["public"]  # the change happened

    [rollback] = [
        x
        for x in client.get(f"/api/proposals?conversation_id={conv_id}").json()["data"]
        if x["kind"] == "rollback"
    ]
    assert rollback["parent_id"] == pid and rollback["status"] == "PENDING_APPROVAL"
    _decide(client, rollback["id"], "approve")  # the rollback needs an approval too
    assert client.get(f"/api/proposals/{rollback['id']}").json()["data"]["status"] == "SUCCEEDED"
    assert client.get(f"/api/proposals/{pid}").json()["data"]["status"] == "ROLLED_BACK"
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["private"]


def test_refused_proposals_are_reported_not_stored(client, connection, kb1, monkeypatch):
    open_ssh = {
        "action": "authorize_sg_ingress",
        "params": {"group_id": kb1["sg"], "port": 22, "cidr": "0.0.0.0/0"},
        "reason": "Mở SSH",
    }
    unknown = {"action": "terminate_instances", "params": {}, "reason": "?"}
    conv_id, answer, _ = _ask(client, connection, monkeypatch, [open_ssh])
    [ref] = answer["proposals"]
    assert ref["proposal_id"] is None and "never opened to the whole Internet" in ref["error"]
    assert client.get(f"/api/proposals?conversation_id={conv_id}").json()["data"] == []

    # an action outside the catalogue cannot even be submitted
    _, answer, _ = _ask(client, connection, monkeypatch, [unknown])
    assert answer is None or answer["proposals"][0]["error"]


def test_connection_without_remediation_gets_no_proposals(client, connection, kb1, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "remediation_allow_access_keys", False)
    assert (
        client.get(f"/api/connections/{connection['id']}").json()["data"]["remediation_enabled"]
        is False
    )
    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    [ref] = answer["proposals"]
    assert ref["proposal_id"] is None and "not enabled" in ref["error"]


def test_approving_after_remediation_was_turned_off_is_refused(
    client, connection, kb1, monkeypatch
):
    from app.config import get_settings

    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pid = answer["proposals"][0]["proposal_id"]
    monkeypatch.setattr(get_settings(), "remediation_allow_access_keys", False)
    body = _decide(client, pid, "approve")
    assert body["status_code"] == 400 and body["error"] == "REMEDIATION_DISABLED"
    assert client.get(f"/api/proposals/{pid}").json()["data"]["status"] == "PENDING_APPROVAL"


def test_pending_proposals_expire(client, connection, kb1, monkeypatch, app):
    from app.storage.store import open_store

    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pid = answer["proposals"][0]["proposal_id"]
    with open_store() as store:
        p = store.get_proposal(pid)
        p.expires_at = utcnow() - timedelta(minutes=1)
        store.update_proposal(p)
    assert client.get(f"/api/proposals/{pid}").json()["data"]["status"] == "EXPIRED"
    assert _decide(client, pid, "approve")["error"] == "PROPOSAL_NOT_PENDING"


def test_role_connection_remediation_role(client):
    created = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "prod",
            "region": "ap-southeast-1",
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
        },
    ).json()["data"]
    assert created["remediation_enabled"] is False
    updated = client.patch(
        f"/api/connections/{created['id']}",
        json={"remediation_role_arn": "arn:aws:iam::123456789012:role/AutoAWSRemediation"},
    ).json()["data"]
    assert updated["remediation_enabled"] is True
    assert updated["remediation_role_arn"].endswith("AutoAWSRemediation")
    off = client.patch(f"/api/connections/{created['id']}", json={"remediation_role_arn": None})
    assert off.json()["data"]["remediation_enabled"] is False


def test_actions_catalogue_endpoint(client):
    actions = client.get("/api/remediation/actions").json()["data"]
    names = {a["name"] for a in actions}
    assert "associate_route_table" in names and len(actions) == 6
    sg = next(a for a in actions if a["name"] == "authorize_sg_ingress")
    assert sg["aws_actions"] == [
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupIngress",
    ]
