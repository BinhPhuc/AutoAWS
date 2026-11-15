# ruff: noqa: F811  (pytest fixtures imported from the flow tests are re-declared as arguments)
"""Editing a proposal's parameters (docs/API_CONTRACT.md §7, POST /proposals/{id}/revise):
a NEW proposal goes through the same schema check, pre-checks and preview; nothing is
written until that new proposal is approved."""

import json

from tests.test_remediation_flow import (  # noqa: F401 (fixtures)
    _ask,
    _current_rt,
    _decide,
    _fix,
    kb1,
    remediation_on,
)
from tests.test_serverless import lambda_runtime  # noqa: F401 (fixture)


def _revise(client, pid: str, params: dict):
    return client.post(f"/api/proposals/{pid}/revise", json={"params": params}).json()


def _other_public_table(kb1) -> str:
    """A second route table with an Internet route, the "edited" target."""
    ec2 = kb1["ec2"]
    vpc = ec2.describe_subnets(SubnetIds=[kb1["subnet"]])["Subnets"][0]["VpcId"]
    igw = ec2.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc]}])[
        "InternetGateways"
    ][0]["InternetGatewayId"]
    rt = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=rt, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
    return rt


def _pending(client, connection, kb1, monkeypatch) -> str:
    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    return answer["proposals"][0]["proposal_id"]


def test_a_revision_replaces_the_pending_proposal(client, connection, kb1, monkeypatch):
    pid = _pending(client, connection, kb1, monkeypatch)
    other = _other_public_table(kb1)

    body = _revise(client, pid, {"subnet_id": kb1["subnet"], "route_table_id": other})
    assert (body["status_code"], body["message"]) == (201, "Proposal revised")
    new = body["data"]
    assert new["parent_id"] == pid and new["kind"] == "fix" and new["status"] == "PENDING_APPROVAL"
    assert new["params"]["route_table_id"] == other
    assert other in new["preview"]["changes"][0]["after"]  # preview recomputed
    assert new["history"][-1]["note"] == f"revised by the user from {pid}"
    assert new["history"][-1]["by"] == "local"

    old = client.get(f"/api/proposals/{pid}").json()["data"]
    assert old["status"] == "SUPERSEDED"
    assert old["history"][-1]["note"] == "edited by the user"
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["private"]  # nothing written yet

    assert _decide(client, pid, "approve")["error"] == "PROPOSAL_NOT_PENDING"
    _decide(client, new["id"], "approve")
    assert client.get(f"/api/proposals/{new['id']}").json()["data"]["status"] == "SUCCEEDED"
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == other


def test_failed_checks_leave_the_original_waiting(client, connection, kb1, monkeypatch):
    pid = _pending(client, connection, kb1, monkeypatch)
    # pre-check: the subnet already uses the private table (nothing would change)
    body = _revise(client, pid, {"subnet_id": kb1["subnet"], "route_table_id": kb1["private"]})
    assert body["status_code"] == 422 and body["error"] == "VALIDATION_ERROR"
    assert "already uses" in body["message"]
    # schema: not a route table id / missing field
    for params in (
        {"subnet_id": kb1["subnet"], "route_table_id": "not-a-table"},
        {"subnet_id": kb1["subnet"]},
    ):
        body = _revise(client, pid, params)
        assert body["status_code"] == 422 and body["error"] == "VALIDATION_ERROR", params
    assert client.get(f"/api/proposals/{pid}").json()["data"]["status"] == "PENDING_APPROVAL"
    listed = client.get("/api/proposals").json()["data"]
    assert not [p for p in listed if p["parent_id"] == pid]


def test_rejected_and_stale_proposals_can_be_edited(client, connection, kb1, monkeypatch):
    params = {"subnet_id": kb1["subnet"], "route_table_id": kb1["public"]}
    pid = _pending(client, connection, kb1, monkeypatch)
    _decide(client, pid, "reject")
    new = _revise(client, pid, params)["data"]
    assert new["status"] == "PENDING_APPROVAL"
    # a rejected original stays rejected (only a pending one is superseded)
    assert client.get(f"/api/proposals/{pid}").json()["data"]["status"] == "REJECTED"

    # STALE: changed by hand after the preview -> a revision starts from the new state
    ec2 = kb1["ec2"]
    assoc = ec2.describe_route_tables(RouteTableIds=[kb1["private"]])["RouteTables"][0][
        "Associations"
    ][0]["RouteTableAssociationId"]
    third = _other_public_table(kb1)
    ec2.replace_route_table_association(AssociationId=assoc, RouteTableId=third)
    _decide(client, new["id"], "approve")
    assert client.get(f"/api/proposals/{new['id']}").json()["data"]["status"] == "STALE"
    again = _revise(client, new["id"], params)["data"]
    assert third in again["preview"]["changes"][0]["before"]


def test_applied_proposals_cannot_be_edited(client, connection, kb1, monkeypatch):
    pid = _pending(client, connection, kb1, monkeypatch)
    _decide(client, pid, "approve")
    body = _revise(client, pid, {"subnet_id": kb1["subnet"], "route_table_id": kb1["public"]})
    assert (body["status_code"], body["error"]) == (409, "PROPOSAL_NOT_EDITABLE")


def test_rollbacks_cannot_be_edited(store, connection):
    from app.errors import AppError
    from app.remediation import service
    from app.storage.models import Proposal

    rollback = store.create_proposal(
        Proposal(
            user_id="local",
            conversation_id="conv_x",
            connection_id=connection["id"],
            action="route_table_associate",
            kind="rollback",
            parent_id="prop_x",
            status="PENDING_APPROVAL",
        )
    )
    try:
        service.revise(store, rollback.id, {})
    except AppError as e:
        assert (e.status, e.error) == (409, "PROPOSAL_NOT_EDITABLE")
    else:
        raise AssertionError("a rollback was revised")


def test_revising_needs_remediation_on(client, connection, kb1, monkeypatch):
    from app.config import get_settings

    pid = _pending(client, connection, kb1, monkeypatch)
    monkeypatch.setattr(get_settings(), "remediation_allow_access_keys", False)
    body = _revise(client, pid, {"subnet_id": kb1["subnet"], "route_table_id": kb1["public"]})
    assert (body["status_code"], body["error"]) == (400, "REMEDIATION_DISABLED")


def test_unknown_proposal(client):
    body = _revise(client, "prop_missing", {})
    assert (body["status_code"], body["error"]) == (404, "PROPOSAL_NOT_FOUND")


def test_on_lambda_the_agent_worker_revises(
    client,
    connection,
    kb1,
    monkeypatch,
    lambda_runtime,  # noqa: F811
):
    """api-handler cannot assume users' roles: it invokes agent-worker synchronously and
    hands its result (or its error) back unchanged."""
    from app.handlers import agent_worker
    from app.platform import dispatch

    monkeypatch.setattr(dispatch.get_settings(), "runtime", "local")
    pid = _pending(client, connection, kb1, monkeypatch)
    monkeypatch.setattr(dispatch.get_settings(), "runtime", "lambda")

    # the worker refuses: same envelope as locally
    lambda_runtime.verify_payload = agent_worker.handler(
        {"mode": "revise", "proposal_id": pid, "params": {"subnet_id": kb1["subnet"]}, "by": "x"}
    )
    body = _revise(client, pid, {"subnet_id": kb1["subnet"]})
    assert (body["status_code"], body["error"]) == (422, "VALIDATION_ERROR")
    sync = [k for op, k in lambda_runtime.calls if k.get("InvocationType") == "RequestResponse"]
    assert json.loads(sync[-1]["Payload"]) == {
        "mode": "revise",
        "proposal_id": pid,
        "params": {"subnet_id": kb1["subnet"]},
        "by": "local",
    }

    # the worker succeeds: the API returns the proposal it created
    params = {"subnet_id": kb1["subnet"], "route_table_id": kb1["public"]}
    monkeypatch.setattr(dispatch.get_settings(), "runtime", "local")
    result = agent_worker.handler(
        {"mode": "revise", "proposal_id": pid, "params": params, "by": "x"}
    )
    monkeypatch.setattr(dispatch.get_settings(), "runtime", "lambda")
    assert result["ok"] is True
    lambda_runtime.verify_payload = result
    body = _revise(client, pid, params)
    assert body["status_code"] == 201 and body["data"]["id"] == result["proposal_id"]
