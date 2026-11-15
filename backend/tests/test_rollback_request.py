# ruff: noqa: F811  (pytest fixtures imported from the flow tests are re-declared as arguments)
"""The user undoes an applied fix (docs/API_CONTRACT.md §7, POST /proposals/{id}/rollback):
a rollback proposal that must be approved, built from the resource's current state."""

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


def _rollback(client, pid: str):
    return client.post(f"/api/proposals/{pid}/rollback").json()


def _applied(client, connection, kb1, monkeypatch) -> str:
    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pid = answer["proposals"][0]["proposal_id"]
    _decide(client, pid, "approve")
    assert client.get(f"/api/proposals/{pid}").json()["data"]["status"] == "SUCCEEDED"
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["public"]
    return pid


def _get(client, pid: str) -> dict:
    return client.get(f"/api/proposals/{pid}").json()["data"]


def test_undo_an_applied_fix_after_approval(client, connection, kb1, monkeypatch):
    pid = _applied(client, connection, kb1, monkeypatch)

    body = _rollback(client, pid)
    assert (body["status_code"], body["message"]) == (201, "Rollback proposed")
    rb = body["data"]
    assert (rb["kind"], rb["parent_id"], rb["status"]) == ("rollback", pid, "PENDING_APPROVAL")
    assert rb["action"] == "route_table_associate"
    assert rb["preview"]["summary"].startswith(f"Undo {pid}:")
    assert rb["history"][0]["note"] == "rollback requested by the user"
    assert rb["history"][0]["by"] == "local"
    # nothing is undone before the approval
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["public"]
    assert _get(client, pid)["status"] == "SUCCEEDED"

    _decide(client, rb["id"], "approve")
    rb = _get(client, rb["id"])
    assert rb["status"] == "SUCCEEDED" and rb["verification"]["ok"] is True
    assert _get(client, pid)["status"] == "ROLLED_BACK"
    assert _current_rt(kb1["ec2"], kb1["subnet"]) == kb1["private"]
    # rolled back: nothing left to undo
    assert _rollback(client, pid)["error"] == "PROPOSAL_NOT_ROLLBACKABLE"


def test_one_rollback_at_a_time(client, connection, kb1, monkeypatch):
    pid = _applied(client, connection, kb1, monkeypatch)
    first = _rollback(client, pid)["data"]
    again = _rollback(client, pid)
    assert (again["status_code"], again["error"]) == (409, "PROPOSAL_NOT_ROLLBACKABLE")
    assert "already waiting or running" in again["message"]
    # a rejected rollback frees the way for a new request
    _decide(client, first["id"], "reject")
    assert _rollback(client, pid)["status_code"] == 201


def test_only_applied_fixes(client, connection, kb1, monkeypatch):
    _, answer, _ = _ask(client, connection, monkeypatch, [_fix(kb1)])
    pending = answer["proposals"][0]["proposal_id"]
    body = _rollback(client, pending)
    assert (body["status_code"], body["error"]) == (409, "PROPOSAL_NOT_ROLLBACKABLE")
    assert body["message"] == "Only applied fixes can be rolled back"

    pid = _applied(client, connection, kb1, monkeypatch)
    rb = _rollback(client, pid)["data"]
    assert _rollback(client, rb["id"])["error"] == "PROPOSAL_NOT_ROLLBACKABLE"  # of a rollback


def test_a_later_change_by_someone_else_is_not_overwritten(client, connection, kb1, monkeypatch):
    pid = _applied(client, connection, kb1, monkeypatch)
    rb = _rollback(client, pid)["data"]
    # someone moves the subnet again after the rollback was proposed
    ec2 = kb1["ec2"]
    vpc = ec2.describe_subnets(SubnetIds=[kb1["subnet"]])["Subnets"][0]["VpcId"]
    other = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    assoc = ec2.describe_route_tables(RouteTableIds=[kb1["public"]])["RouteTables"][0][
        "Associations"
    ][0]["RouteTableAssociationId"]
    ec2.replace_route_table_association(AssociationId=assoc, RouteTableId=other)

    _decide(client, rb["id"], "approve")
    assert _get(client, rb["id"])["status"] == "STALE"
    assert _get(client, pid)["status"] == "SUCCEEDED"
    assert _current_rt(ec2, kb1["subnet"]) == other


def test_a_deleted_resource_cannot_be_rolled_back(client, connection, kb1, monkeypatch):
    pid = _applied(client, connection, kb1, monkeypatch)
    ec2 = kb1["ec2"]
    assoc = ec2.describe_route_tables(RouteTableIds=[kb1["public"]])["RouteTables"][0][
        "Associations"
    ][0]["RouteTableAssociationId"]
    ec2.disassociate_route_table(AssociationId=assoc)
    ec2.delete_subnet(SubnetId=kb1["subnet"])
    body = _rollback(client, pid)
    assert (body["status_code"], body["error"]) == (409, "PROPOSAL_NOT_ROLLBACKABLE")
    assert body["message"].startswith("The resource can no longer be read")


def test_rollback_needs_remediation_on(client, connection, kb1, monkeypatch):
    from app.config import get_settings

    pid = _applied(client, connection, kb1, monkeypatch)
    monkeypatch.setattr(get_settings(), "remediation_allow_access_keys", False)
    body = _rollback(client, pid)
    assert (body["status_code"], body["error"]) == (400, "REMEDIATION_DISABLED")


def test_unknown_proposal(client):
    body = _rollback(client, "prop_missing")
    assert (body["status_code"], body["error"]) == (404, "PROPOSAL_NOT_FOUND")


def test_on_lambda_the_agent_worker_proposes_the_rollback(
    client, connection, kb1, monkeypatch, lambda_runtime
):
    from app.handlers import agent_worker
    from app.platform import dispatch

    settings = dispatch.get_settings()
    monkeypatch.setattr(settings, "runtime", "local")
    pid = _applied(client, connection, kb1, monkeypatch)
    result = agent_worker.handler({"mode": "rollback", "proposal_id": pid, "by": "local"})
    assert result["ok"] is True
    monkeypatch.setattr(settings, "runtime", "lambda")

    lambda_runtime.verify_payload = result
    body = _rollback(client, pid)
    assert body["status_code"] == 201 and body["data"]["id"] == result["proposal_id"]
    sync = [k for op, k in lambda_runtime.calls if k.get("InvocationType") == "RequestResponse"]
    assert json.loads(sync[-1]["Payload"]) == {
        "mode": "rollback",
        "proposal_id": pid,
        "by": "local",
    }

    # the worker's refusal comes back as the same error (a second request while one waits)
    monkeypatch.setattr(settings, "runtime", "local")
    lambda_runtime.verify_payload = agent_worker.handler(
        {"mode": "rollback", "proposal_id": pid, "by": "local"}
    )
    monkeypatch.setattr(settings, "runtime", "lambda")
    body = _rollback(client, pid)
    assert (body["status_code"], body["error"]) == (409, "PROPOSAL_NOT_ROLLBACKABLE")


def test_action_without_automatic_undo_cannot_be_rolled_back(client, connection, kb1, monkeypatch):
    """Starting an instance has no undo: AutoAWS never stops instances."""
    ec2 = kb1["ec2"]
    instance = ec2.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=kb1["subnet"]
    )["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[instance])
    start = {"action": "instance_start", "params": {"instance_id": instance}, "reason": "Bật lại"}
    _, answer, _ = _ask(client, connection, monkeypatch, [start])
    pid = answer["proposals"][0]["proposal_id"]
    assert "No automatic undo" in _get(client, pid)["preview"]["rollback"]
    _decide(client, pid, "approve")
    assert _get(client, pid)["status"] == "SUCCEEDED"
    state = ec2.describe_instances(InstanceIds=[instance])["Reservations"][0]["Instances"][0]
    assert state["State"]["Name"] == "running"

    body = _rollback(client, pid)
    assert (body["status_code"], body["error"]) == (409, "PROPOSAL_NOT_ROLLBACKABLE")
    assert "no automatic undo" in body["message"]
    assert _get(client, pid)["status"] == "SUCCEEDED"
