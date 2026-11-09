"""Jobs + polling, the Lambda handlers and the RUNTIME=lambda dispatch (Lambda invoke, Step
Functions remediation-flow) — docs/API_CONTRACT.md §8–§9. No AWS: platform clients are fakes."""

import io
import json
from datetime import timedelta

import pytest

from app.agent.schemas import DiagnosisAnswer, ProposalRef
from app.llm.base import LLMResponse, ToolCallRequest
from app.platform import dispatch
from app.storage.models import Conversation, Job, utcnow
from tests.conftest import ask


class FakePlatform:
    """Records Lambda / Step Functions calls made through app.platform.dispatch."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.verify_payload: dict = {}

    def __call__(self, service: str):
        outer = self

        class Client:
            def __getattr__(self, op):
                def call(**kwargs):
                    outer.calls.append((f"{service}.{op}", kwargs))
                    if op == "invoke" and kwargs.get("InvocationType") == "RequestResponse":
                        return {"Payload": io.BytesIO(json.dumps(outer.verify_payload).encode())}
                    return {}

                return call

        return Client()

    def ops(self) -> list[str]:
        return [op for op, _ in self.calls]


@pytest.fixture
def lambda_runtime(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "runtime", "lambda")
    monkeypatch.setattr(settings, "agent_worker_function", "autoaws-agent-worker")
    monkeypatch.setattr(
        settings, "remediation_state_machine_arn", "arn:aws:states:ap-southeast-1:1:stateMachine:rf"
    )
    fake = FakePlatform()
    monkeypatch.setattr(dispatch, "_client", fake)
    return fake


def _conversation(client, connection) -> str:
    return client.post("/api/conversations", json={"connection_id": connection["id"]}).json()[
        "data"
    ]["id"]


# ---- jobs (RUNTIME=local) ---------------------------------------------------------------


def test_job_lifecycle_and_polling(client, connection):
    conv_id = _conversation(client, connection)
    r = client.post(f"/api/conversations/{conv_id}/messages", json={"content": "Không SSH được"})
    assert r.status_code == 202 and r.json()["message"] == "Diagnosis started"
    job = r.json()["data"]
    assert job["status"] == "queued" and job["conversation_id"] == conv_id

    done = client.get(f"/api/jobs/{job['id']}").json()["data"]
    assert done["status"] == "succeeded" and done["message_id"]
    types = [e["type"] for e in done["events"]]
    assert types[0] == "status" and types[-2:] == ["answer", "done"]
    assert [e["seq"] for e in done["events"]] == list(range(len(types)))

    # ?after=<seq> returns only newer events
    tail = client.get(f"/api/jobs/{job['id']}?after={len(types) - 3}").json()["data"]["events"]
    assert [e["type"] for e in tail] == ["answer", "done"]

    messages = client.get(f"/api/conversations/{conv_id}").json()["data"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["id"] == done["message_id"]

    assert client.get("/api/jobs/job_nope").json()["error"] == "JOB_NOT_FOUND"


def test_one_running_job_per_conversation(client, connection, app):
    from app.storage.store import open_store

    conv_id = _conversation(client, connection)
    with open_store() as store:
        conv = store.get_conversation(conv_id)
        store.create_job(Job(conversation_id=conv.id, question="q", status="running"))
    r = client.post(f"/api/conversations/{conv_id}/messages", json={"content": "lần hai"})
    assert r.status_code == 409 and r.json()["error"] == "JOB_IN_PROGRESS"


def test_lost_worker_is_reported_and_the_turn_closed(client, connection, app):
    from app.storage.models import Message
    from app.storage.store import open_store

    conv_id = _conversation(client, connection)
    with open_store() as store:
        store.add_message(Message(conversation_id=conv_id, role="user", content="câu hỏi"))
        job_id = store.create_job(
            Job(conversation_id=conv_id, question="câu hỏi", status="running")
        ).id
        old = utcnow() - timedelta(hours=1)
        if hasattr(store, "db"):  # SQLite: backdate updated_at
            from sqlalchemy import update

            store.db.exec(update(Job).where(Job.id == job_id).values(updated_at=old))
            store.db.commit()
    got = client.get(f"/api/jobs/{job_id}").json()["data"]
    assert got["status"] == "failed" and got["error"]["error"] == "WORKER_LOST"
    messages = client.get(f"/api/conversations/{conv_id}").json()["data"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    # the conversation accepts a new question again
    assert (
        client.post(f"/api/conversations/{conv_id}/messages", json={"content": "lại"}).status_code
        == 202
    )


async def test_cancel_stops_the_turn(store, aws):
    from app import worker

    class ToolsForever:
        name = "loop"
        enforce_time_limit = True

        async def chat(self, messages, tools):
            call = ToolCallRequest(id=f"t{len(messages)}", name="get_caller_identity")
            return LLMResponse(tool_calls=[call], stop_reason="tool_use")

    from app.storage.models import Connection

    conn = store.create_connection(
        Connection(
            name="c",
            type="access_key",
            region="ap-southeast-1",
            status="connected",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="x" * 20,
        )
    )
    conv = store.create_conversation(Conversation(connection_id=conn.id))
    job = store.create_job(Job(conversation_id=conv.id, question="kiểm tra", cancel_requested=True))

    import contextlib

    @contextlib.contextmanager
    def same_store():
        yield store

    import app.worker as worker_module

    original = worker_module.open_store
    worker_module.open_store = same_store
    original_provider = worker_module.get_provider
    worker_module.get_provider = lambda: ToolsForever()
    try:
        await worker.run_job(job.id)
    finally:
        worker_module.open_store = original
        worker_module.get_provider = original_provider
    got = store.get_job(job.id)
    assert got.status == "cancelled"
    events = json.loads(got.events_json)
    assert events[-2]["data"]["error"] == "CANCELLED" and events[-1]["type"] == "done"
    roles = [m.role for m in store.list_messages(conv.id)]
    assert roles == ["user", "assistant"]


def test_llm_unavailable_before_start_keeps_history(client, connection, monkeypatch):
    from app import worker
    from app.llm.base import LLMError

    def broken():
        raise LLMError("BEDROCK_MODEL_ID is not set")

    monkeypatch.setattr(worker, "get_provider", broken)
    conv_id = _conversation(client, connection)
    job, events = ask(client, conv_id, "Website lỗi")
    assert job["status"] == "failed" and job["error"]["error"] == "LLM_UNAVAILABLE"
    messages = client.get(f"/api/conversations/{conv_id}").json()["data"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"].startswith("Chưa hoàn thành chẩn đoán")


# ---- RUNTIME=lambda dispatch ------------------------------------------------------------


def test_lambda_runtime_hands_jobs_and_verify_to_agent_worker(client, connection, lambda_runtime):
    conv_id = _conversation(client, connection)
    r = client.post(f"/api/conversations/{conv_id}/messages", json={"content": "Không SSH được"})
    assert r.status_code == 202
    job_id = r.json()["data"]["id"]
    [(op, kwargs)] = [c for c in lambda_runtime.calls if c[0] == "lambda.invoke"]
    assert kwargs["FunctionName"] == "autoaws-agent-worker" and kwargs["InvocationType"] == "Event"
    assert json.loads(kwargs["Payload"]) == {"mode": "diagnosis", "job_id": job_id}
    # nothing ran in the API process: the job waits for the worker
    assert client.get(f"/api/jobs/{job_id}").json()["data"]["status"] == "queued"

    lambda_runtime.verify_payload = {
        "status": "connected",
        "account_id": "123456789012",
        "arn": "arn:aws:sts::123456789012:assumed-role/AutoAWSReadOnly/x",
        "checked_at": "2026-11-09T00:00:00Z",
        "error": None,
    }
    v = client.post(f"/api/connections/{connection['id']}/verify").json()
    assert v["data"]["status"] == "connected"
    sync = [k for op, k in lambda_runtime.calls if k.get("InvocationType") == "RequestResponse"]
    assert json.loads(sync[0]["Payload"]) == {"mode": "verify", "connection_id": connection["id"]}


def test_agent_worker_runs_the_job(client, connection):
    from app.handlers import agent_worker
    from app.storage.store import open_store

    conv_id = _conversation(client, connection)
    with open_store() as store:
        conv = store.get_conversation(conv_id)
        job = store.create_job(Job(conversation_id=conv.id, question="Không SSH được"))
    assert agent_worker.handler({"mode": "diagnosis", "job_id": job.id}) == {"ok": True}
    assert client.get(f"/api/jobs/{job.id}").json()["data"]["status"] == "succeeded"
    out = agent_worker.handler({"mode": "verify", "connection_id": connection["id"]})
    assert out["status"] == "connected"
    with pytest.raises(ValueError):
        agent_worker.handler({"mode": "rm"})


def test_api_handler_serves_api_gateway_events(app):
    from app.handlers.api import handler

    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/api/health",
        "rawQueryString": "",
        "headers": {"host": "x.execute-api.ap-southeast-1.amazonaws.com"},
        "requestContext": {
            "http": {"method": "GET", "path": "/api/health", "sourceIp": "1.2.3.4"},
            "stage": "$default",
            "requestId": "r",
        },
        "isBase64Encoded": False,
    }
    resp = handler(event, None)
    assert resp["statusCode"] == 200 and json.loads(resp["body"])["data"]["status"] == "ok"


# ---- remediation-flow, step by step (what Step Functions runs) ----------------------------


@pytest.fixture
def kb1_proposal(store, aws, monkeypatch):
    from app.config import get_settings
    from app.storage.models import Connection

    settings = get_settings()
    monkeypatch.setattr(settings, "remediation_allow_access_keys", True)
    monkeypatch.setattr(settings, "remediation_verify_timeout_seconds", 0)
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
    public = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=public, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
    private = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.associate_route_table(RouteTableId=private, SubnetId=subnet)
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
    answer = DiagnosisAnswer(
        summary="s",
        proposals=[
            ProposalRef(
                action="associate_route_table",
                params={"subnet_id": subnet, "route_table_id": public},
                reason="r",
            )
        ],
    )
    return store, conv, conn, answer, {"ec2": ec2, "subnet": subnet, "public": public}


def _patch_store(monkeypatch, store):
    import contextlib

    import app.handlers.action_executor as ex
    import app.handlers.agent_worker as aw

    @contextlib.contextmanager
    def same():
        yield store

    monkeypatch.setattr(aw, "open_store", same)
    monkeypatch.setattr(ex, "open_store", same)


def test_remediation_flow_steps(kb1_proposal, lambda_runtime, monkeypatch, aws):
    from app.handlers import action_executor, agent_worker
    from app.remediation.service import attach_proposals, decide

    store, conv, conn, answer, n = kb1_proposal
    _patch_store(monkeypatch, store)
    attach_proposals(store, conv, "msg_1", conn, aws, answer)
    pid = answer.proposals[0].proposal_id
    [(op, start)] = [c for c in lambda_runtime.calls if c[0] == "stepfunctions.start_execution"]
    assert start["name"] == pid and json.loads(start["input"])["proposal_id"] == pid

    # 1. the flow waits for the decision: the token is stored, nothing is sent yet
    out = action_executor.handler({"mode": "store_token", "proposal_id": pid, "task_token": "T1"})
    assert out["status"] == "PENDING_APPROVAL"
    assert "stepfunctions.send_task_success" not in lambda_runtime.ops()
    # 2. the user approves (api-handler): the decision resumes the flow, no write yet
    decide(store, store.get_proposal(pid), "approve")
    [(op, sent)] = [c for c in lambda_runtime.calls if c[0] == "stepfunctions.send_task_success"]
    assert sent["taskToken"] == "T1"
    assert store.get_proposal(pid).status == "APPROVED"
    # 3. agent-worker re-checks, 4. action-executor writes, 5. agent-worker verifies
    assert agent_worker.handler({"mode": "recheck", "proposal_id": pid})["ok"] is True
    assert action_executor.handler({"mode": "execute", "proposal_id": pid})["ok"] is True
    again = action_executor.handler({"mode": "execute", "proposal_id": pid})  # retried state
    assert again["ok"] is True
    final = agent_worker.handler({"mode": "verify_proposal", "proposal_id": pid})
    assert final == {"ok": True, "status": "SUCCEEDED"}
    rts = n["ec2"].describe_route_tables(
        Filters=[{"Name": "association.subnet-id", "Values": [n["subnet"]]}]
    )["RouteTables"]
    assert rts[0]["RouteTableId"] == n["public"]
    # the token never leaves the server
    from app.api.schemas import ProposalOut

    assert "task_token" not in ProposalOut.from_model(store.get_proposal(pid)).model_dump()


def test_decision_before_the_token_is_delivered_when_it_arrives(
    kb1_proposal, lambda_runtime, monkeypatch, aws
):
    from app.handlers import action_executor
    from app.remediation.service import attach_proposals, decide

    store, conv, conn, answer, _ = kb1_proposal
    _patch_store(monkeypatch, store)
    attach_proposals(store, conv, "msg_1", conn, aws, answer)
    pid = answer.proposals[0].proposal_id
    decide(store, store.get_proposal(pid), "reject")  # no token yet: nothing to send
    assert "stepfunctions.send_task_failure" not in lambda_runtime.ops()
    action_executor.handler({"mode": "store_token", "proposal_id": pid, "task_token": "T2"})
    [(op, sent)] = [c for c in lambda_runtime.calls if c[0] == "stepfunctions.send_task_failure"]
    assert sent["taskToken"] == "T2" and sent["error"] == "REJECTED"


def test_approval_timeout_expires(kb1_proposal, lambda_runtime, monkeypatch, aws):
    from app.handlers import agent_worker
    from app.remediation.service import attach_proposals

    store, conv, conn, answer, _ = kb1_proposal
    _patch_store(monkeypatch, store)
    attach_proposals(store, conv, "msg_1", conn, aws, answer)
    pid = answer.proposals[0].proposal_id
    assert agent_worker.handler({"mode": "expire", "proposal_id": pid})["status"] == "EXPIRED"


def test_customer_template_trusts_only_the_platform_roles(client, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "platform_aws_account_id", "111122223333")
    monkeypatch.setattr(
        settings, "platform_agent_role_arn", "arn:aws:iam::111122223333:role/autoaws-agent-worker"
    )
    monkeypatch.setattr(
        settings,
        "platform_executor_role_arn",
        "arn:aws:iam::111122223333:role/autoaws-action-executor",
    )
    conn = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "prod",
            "region": "ap-southeast-1",
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
        },
    ).json()["data"]
    yaml = client.get(f"/api/connections/{conn['id']}/cloudformation").json()["data"][
        "template_yaml"
    ]
    read, remediation = yaml.split("  AutoAWSRemediationRole:", 1)
    assert ":root" not in yaml
    assert "role/autoaws-agent-worker" in read and "role/autoaws-action-executor" in read
    assert "role/autoaws-agent-worker" not in remediation
    assert "role/autoaws-action-executor" in remediation
