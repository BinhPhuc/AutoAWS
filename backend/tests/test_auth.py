"""Real RSA JWT verification and tenant isolation on both storage backends."""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings, get_settings
from app.storage import store as storage
from app.storage.dynamo import DynamoStore, ensure_table
from app.storage.models import Connection, Conversation, Job, Message, Proposal, ToolCallRecord
from app.storage.sql import SqlStore
from tests.conftest import FAKE_KEY, FAKE_SECRET, REGION, ask

ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_Test"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def tokens(monkeypatch, signing_key):
    monkeypatch.setattr(
        auth,
        "jwks_client",
        lambda issuer: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=signing_key.public_key())
        ),
    )

    def issue(user_id="alice", **overrides):
        claims = {
            "sub": user_id,
            "username": user_id,
            "iss": ISSUER,
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "client_id": "web-client",
            "token_use": "access",
            "scope": "openid email",
            **overrides,
        }
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test"})

    return issue


@pytest.fixture(params=["sqlite", "dynamodb"])
def authenticated_api(request, app, aws, monkeypatch, tokens):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "cognito")
    monkeypatch.setattr(settings, "cognito_issuer", ISSUER)
    monkeypatch.setattr(settings, "cognito_client_id", "web-client")
    monkeypatch.setattr(
        settings, "cognito_domain", "https://example.auth.ap-southeast-1.amazoncognito.com"
    )
    if request.param == "dynamodb":
        ddb = aws.client("dynamodb")
        ensure_table(ddb, "auth-test")
        monkeypatch.setattr(settings, "storage_backend", "dynamodb")
        monkeypatch.setattr(settings, "dynamodb_table", "auth-test")
        monkeypatch.setattr(storage, "dynamodb_client", lambda: ddb)
    with TestClient(app) as api:
        yield api


def headers(tokens, user_id="alice", **claims):
    return {"Authorization": f"Bearer {tokens(user_id, **claims)}"}


def test_public_config_and_protected_routes(authenticated_api, tokens):
    api = authenticated_api
    assert api.get("/api/health").status_code == 200
    config = api.get("/api/auth/config").json()["data"]
    assert config == {
        "mode": "cognito",
        "issuer": ISSUER,
        "client_id": "web-client",
        "domain": "https://example.auth.ap-southeast-1.amazoncognito.com",
    }
    for path in (
        "/api/auth/me",
        "/api/connections",
        "/api/conversations",
        "/api/proposals",
        "/api/tools",
        "/api/remediation/actions",
        "/api/checklists",
    ):
        result = api.get(path, headers={"X-User-Id": "alice"})
        assert result.status_code == 401
        assert result.headers["WWW-Authenticate"] == "Bearer"
        assert set(result.json()) == {"status_code", "message", "error", "path", "timestamp"}
    assert api.get("/api/auth/me", headers=headers(tokens)).json()["data"]["user_id"] == "alice"


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": 1},
        {"iss": "https://attacker.example"},
        {"client_id": "another-app"},
        {"token_use": "id"},
        {"scope": "email"},
        {"sub": "alice#CONN#"},
        {"iat": 9999999999},
        {"sub": ""},
    ],
)
def test_invalid_claims_are_rejected(client, monkeypatch, tokens, claims):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "cognito")
    monkeypatch.setattr(settings, "cognito_issuer", ISSUER)
    monkeypatch.setattr(settings, "cognito_client_id", "web-client")
    assert client.get("/api/auth/me", headers=headers(tokens, **claims)).status_code == 401


def test_invalid_signature_and_jwks_outage(client, monkeypatch, tokens):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "cognito")
    monkeypatch.setattr(settings, "cognito_issuer", ISSUER)
    monkeypatch.setattr(settings, "cognito_client_id", "web-client")
    valid = tokens()
    forged = valid.rsplit(".", 1)[0] + "." + "A" * 342
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    )
    assert (
        client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    )

    def unavailable(token):
        raise auth.PyJWKClientConnectionError("offline")

    monkeypatch.setattr(
        auth, "jwks_client", lambda issuer: SimpleNamespace(get_signing_key_from_jwt=unavailable)
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {valid}"})
    assert response.status_code == 503 and response.json()["error"] == "AUTH_UNAVAILABLE"


def test_tenants_cannot_read_or_mutate_each_other(authenticated_api, tokens):
    api = authenticated_api
    alice, bob = headers(tokens), headers(tokens, "bob")
    conn = api.post(
        "/api/connections",
        headers=alice,
        json={
            "name": "Private",
            "type": "access_key",
            "region": REGION,
            "access_key_id": FAKE_KEY,
            "secret_access_key": FAKE_SECRET,
            "user_id": "bob",
        },
    ).json()["data"]
    cid = conn["id"]
    assert (
        api.post(f"/api/connections/{cid}/verify", headers=alice).json()["data"]["status"]
        == "connected"
    )
    conv = api.post("/api/conversations", headers=alice, json={"connection_id": cid}).json()["data"]
    vid = conv["id"]
    api.headers.update(alice)
    job, _ = ask(api, vid, "Kiểm tra instance")
    api.headers.clear()
    with storage.open_store("alice") as store:
        proposal = store.create_proposal(
            Proposal(conversation_id=vid, connection_id=cid, action="associate_route_table")
        )
        assert store.get_job(job["id"]).user_id == "alice"
        for msg in store.list_messages(vid):
            assert msg.user_id == "alice"
            assert all(tc.user_id == "alice" for tc in store.list_tool_calls(msg.id))
    assert api.get(f"/api/conversations/{vid}", headers=alice).json()["data"]["messages"]
    for path in (
        "/api/connections",
        "/api/conversations",
        "/api/proposals",
        f"/api/conversations?connection_id={cid}",
        f"/api/proposals?conversation_id={vid}",
        "/api/connections?user_id=alice",
    ):
        assert api.get(path, headers=bob).json()["data"] == []
    for method, path, body in (
        ("get", f"/api/connections/{cid}", None),
        ("delete", f"/api/connections/{cid}", None),
        ("post", f"/api/connections/{cid}/verify", None),
        ("get", f"/api/connections/{cid}/cloudformation", None),
        ("patch", f"/api/connections/{cid}", {"remediation_role_arn": None}),
        ("get", f"/api/conversations/{vid}", None),
        ("delete", f"/api/conversations/{vid}", None),
        ("post", "/api/conversations", {"connection_id": cid}),
        ("post", f"/api/conversations/{vid}/messages", {"content": "steal"}),
        ("get", f"/api/jobs/{job['id']}", None),
        ("post", f"/api/jobs/{job['id']}/cancel", None),
        ("get", f"/api/proposals/{proposal.id}", None),
        ("post", f"/api/proposals/{proposal.id}/decision", {"decision": "approve"}),
    ):
        response = api.request(method, path, headers=bob, json=body)
        assert response.status_code == 404, (path, response.text)
    assert api.get(f"/api/connections/{cid}", headers=alice).status_code == 200
    assert (
        api.get(f"/api/proposals/{proposal.id}", headers=alice).json()["data"]["status"]
        == "PENDING_APPROVAL"
    )


def test_stores_isolate_every_entity_and_conditional_writes(store):
    other = (
        DynamoStore(store.client, store.table, "bob")
        if isinstance(store, DynamoStore)
        else SqlStore(store.db, "bob")
    )
    conn = store.create_connection(Connection(name="tenant-test", type="role", region=REGION))
    conv = store.create_conversation(Conversation(connection_id=conn.id))
    msg = store.add_message(
        Message(conversation_id=conv.id, role="assistant"), [ToolCallRecord(tool="x")]
    )
    prop = store.create_proposal(Proposal(conversation_id=conv.id, action="associate_route_table"))
    job = store.create_job(Job(conversation_id=conv.id))
    assert other.get_connection(conn.id) is None
    assert other.get_conversation(conv.id) is None
    assert other.get_proposal(prop.id) is None
    assert other.get_job(job.id) is None
    assert other.list_connections() == other.list_conversations() == other.list_proposals() == []
    assert (
        other.list_messages(conv.id)
        == other.list_tool_calls(msg.id)
        == other.list_jobs(conv.id)
        == []
    )
    with pytest.raises(ValueError, match="Owner mismatch"):
        other.save_connection(conn)
    with pytest.raises(ValueError, match="Owner mismatch"):
        other.update_proposal(prop, expected_status="PENDING_APPROVAL")
    with pytest.raises(ValueError, match="Owner mismatch"):
        other.delete_conversation(conv)
    with pytest.raises(ValueError, match="ownership"):
        store.update_job(job.id, user_id="bob")
    if isinstance(store, DynamoStore):
        items = store.client.scan(TableName=store.table)["Items"]
        assert all(i["PK"]["S"].startswith(f"USER#{store.user_id}#") for i in items)


@pytest.mark.parametrize(
    "changes",
    [
        {"app_env": "prod", "auth_mode": "none"},
        {"runtime": "lambda", "auth_mode": "none"},
        {"auth_mode": "cognito"},
        {"auth_mode": "cognito", "cognito_issuer": "http://attacker"},
    ],
)
def test_unsafe_config_fails_closed(changes):
    with pytest.raises(ValueError):
        auth.validate_auth_settings(Settings(_env_file=None, **changes))


def test_internal_handlers_require_owner():
    from app.handlers import action_executor, agent_worker

    with pytest.raises(KeyError):
        agent_worker.handler({"mode": "diagnosis", "job_id": "j"})
    with pytest.raises(KeyError):
        action_executor.handler({"mode": "execute", "proposal_id": "p"})


def test_aws_session_cache_is_scoped_to_owner(monkeypatch):
    from datetime import timedelta

    from app.aws import credentials
    from app.storage.models import utcnow

    calls = []

    def assume(**kwargs):
        calls.append(kwargs["RoleArn"])
        return {
            "Credentials": {
                "AccessKeyId": FAKE_KEY,
                "SecretAccessKey": FAKE_SECRET,
                "SessionToken": "test-token",
                "Expiration": utcnow() + timedelta(hours=1),
            }
        }

    monkeypatch.setattr(credentials, "_role_cache", {})
    monkeypatch.setattr(
        credentials,
        "platform_session",
        lambda: SimpleNamespace(client=lambda service: SimpleNamespace(assume_role=assume)),
    )
    alice = Connection(
        id="same-id",
        user_id="alice",
        name="A",
        type="role",
        region=REGION,
        role_arn="arn:aws:iam::111111111111:role/AutoAWSReadOnly",
        external_id="a",
    )
    bob = alice.model_copy(update={"user_id": "bob", "external_id": "b"})
    a = credentials.resolve_session(alice)
    b = credentials.resolve_session(bob)
    assert a is not b and len(calls) == 2
    assert credentials.resolve_session(alice) is a
    assert credentials.resolve_session(bob) is b
    credentials.forget_session(alice.id, alice.user_id)
    assert credentials.resolve_session(bob) is b
