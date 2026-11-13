"""Sign-in and per-user data (docs/API_CONTRACT.md §0.1)."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth
from app.storage.models import Connection, Conversation, Job, Proposal

POOL = "ap-southeast-1_TestPool"
ISSUER = f"https://cognito-idp.ap-southeast-1.amazonaws.com/{POOL}"
CLIENT = "webclient123"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(sub: str = "user-a", key=KEY, **claims) -> str:
    now = int(time.time())
    body = {
        "sub": sub,
        "iss": ISSUER,
        "client_id": CLIENT,
        "token_use": "access",
        "username": sub,
        "iat": now,
        "exp": now + 3600,
        **claims,
    }
    return jwt.encode(body, key, algorithm="RS256")


def bearer(sub: str = "user-a", **claims) -> dict:
    return {"Authorization": f"Bearer {token(sub, **claims)}"}


@pytest.fixture
def cognito(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "cognito")
    monkeypatch.setattr(s, "cognito_user_pool_id", POOL)
    monkeypatch.setattr(s, "cognito_client_id", CLIENT)
    monkeypatch.setattr(
        s, "cognito_domain", "https://autodiag-test.auth.ap-southeast-1.amazoncognito.com/"
    )
    monkeypatch.setattr(auth, "signing_key", lambda _t, _s: KEY.public_key())  # no JWKS fetch
    return s


# ---- AUTH_MODE=none ----------------------------------------------------------------------


def test_without_sign_in_everyone_is_the_local_user(client):
    assert client.get("/api/auth/config").json()["data"]["mode"] == "none"
    me = client.get("/api/me").json()["data"]
    assert me == {"user_id": "local", "username": "local", "auth_mode": "none", "is_admin": True}


# ---- AUTH_MODE=cognito -------------------------------------------------------------------


def test_public_routes_and_sign_in_settings(client, cognito):
    assert client.get("/api/health").status_code == 200
    cfg = client.get("/api/auth/config").json()["data"]
    assert cfg == {
        "mode": "cognito",
        "domain": "https://autodiag-test.auth.ap-southeast-1.amazoncognito.com",
        "client_id": CLIENT,
        "scopes": ["openid", "email", "profile"],
    }


@pytest.mark.parametrize("path", ["/api/me", "/api/connections", "/api/tools", "/api/proposals"])
def test_every_other_route_needs_a_token(client, cognito, path):
    r = client.get(path)
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "UNAUTHORIZED" and body["message"] == "Sign in required"
    assert "data" not in body


def test_a_valid_access_token_identifies_the_user(client, cognito):
    me = client.get("/api/me", headers=bearer("user-a")).json()["data"]
    assert me == {
        "user_id": "user-a",
        "username": "user-a",
        "auth_mode": "cognito",
        "is_admin": False,
    }


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": f"Bearer {token(key=OTHER_KEY)}"},  # not signed by the pool
        bearer(exp=int(time.time()) - 600),  # expired
        bearer(iss="https://cognito-idp.ap-southeast-1.amazonaws.com/other_pool"),
        bearer(client_id="someone-elses-client"),
        bearer(token_use="id"),  # ID tokens are not accepted by the API
    ],
    ids=["garbage", "basic", "foreign-key", "expired", "issuer", "client", "id-token"],
)
def test_bad_tokens_are_rejected(client, cognito, headers):
    r = client.get("/api/me", headers=headers)
    assert r.status_code == 401 and r.json()["error"] == "UNAUTHORIZED"


def test_behind_api_gateway_the_authorizer_claims_are_used(app, cognito):
    """RUNTIME=lambda: Mangum passes the event; its claims were checked by the authorizer.
    The same claim checks still run (a wrong client is refused)."""

    def with_claims(claims: dict):
        async def asgi(scope, receive, send):
            if scope["type"] == "http":
                scope["aws.event"] = {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
            await app(scope, receive, send)

        return TestClient(asgi)

    good = {"sub": "user-gw", "iss": ISSUER, "client_id": CLIENT, "token_use": "access"}
    assert with_claims(good).get("/api/me").json()["data"]["user_id"] == "user-gw"
    bad = {**good, "client_id": "other"}
    assert with_claims(bad).get("/api/me").status_code == 401


# ---- per-user data -----------------------------------------------------------------------


@pytest.fixture
def owned_by_a(client, cognito, aws):
    """User A's connection, conversation, job and proposal (made through the API where
    the API can make them)."""
    from app.storage.store import open_store

    a = f"user-a-{uuid.uuid4().hex[:8]}"  # the SQLite test DB is shared between tests

    ext_id = client.get("/api/connections/setup", headers=bearer(a)).json()["data"]["external_id"]
    conn = client.post(
        "/api/connections",
        headers=bearer(a),
        json={
            "type": "role",
            "name": "prod",
            "region": "ap-southeast-1",
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
            "external_id": ext_id,
        },
    ).json()["data"]
    with open_store() as store:
        c = store.get_connection(conn["id"])
        c.status = "connected"
        store.save_connection(c)
    conv = client.post(
        "/api/conversations", headers=bearer(a), json={"connection_id": conn["id"]}
    ).json()["data"]
    with open_store() as store:
        job = store.create_job(Job(user_id=a, conversation_id=conv["id"])).id
        prop = store.create_proposal(
            Proposal(
                user_id=a,
                conversation_id=conv["id"],
                connection_id=conn["id"],
                action="authorize_sg_ingress",
            )
        ).id
    return {"user": a, "conn": conn, "conv": conv, "job": job, "prop": prop, "ext_id": ext_id}


def test_the_external_id_matches_the_role_setup(owned_by_a):
    assert owned_by_a["conn"]["external_id"] == owned_by_a["ext_id"]


def test_the_owner_sees_their_data(client, owned_by_a):
    h = bearer(owned_by_a["user"])
    assert [c["id"] for c in client.get("/api/connections", headers=h).json()["data"]] == [
        owned_by_a["conn"]["id"]
    ]
    convs = client.get("/api/conversations", headers=h).json()["data"]
    assert [c["id"] for c in convs] == [owned_by_a["conv"]["id"]]
    assert client.get(f"/api/jobs/{owned_by_a['job']}", headers=h).status_code == 200
    props = client.get("/api/proposals", headers=h).json()["data"]
    assert [p["id"] for p in props] == [owned_by_a["prop"]]


def test_other_users_see_nothing_and_cannot_touch_it(client, owned_by_a):
    h = bearer("user-b")
    conn, conv = owned_by_a["conn"]["id"], owned_by_a["conv"]["id"]
    job, prop = owned_by_a["job"], owned_by_a["prop"]
    for path in ("/api/connections", "/api/conversations", "/api/proposals"):
        assert client.get(path, headers=h).json()["data"] == [], path
    assert client.get(f"/api/conversations?connection_id={conn}", headers=h).json()["data"] == []
    assert client.get(f"/api/proposals?conversation_id={conv}", headers=h).json()["data"] == []
    not_found = [
        ("GET", f"/api/connections/{conn}", "CONNECTION_NOT_FOUND"),
        ("GET", f"/api/connections/{conn}/cloudformation", "CONNECTION_NOT_FOUND"),
        ("POST", f"/api/connections/{conn}/verify", "CONNECTION_NOT_FOUND"),
        ("DELETE", f"/api/connections/{conn}", "CONNECTION_NOT_FOUND"),
        ("GET", f"/api/conversations/{conv}", "CONVERSATION_NOT_FOUND"),
        ("DELETE", f"/api/conversations/{conv}", "CONVERSATION_NOT_FOUND"),
        ("GET", f"/api/jobs/{job}", "JOB_NOT_FOUND"),
        ("POST", f"/api/jobs/{job}/cancel", "JOB_NOT_FOUND"),
        ("GET", f"/api/proposals/{prop}", "PROPOSAL_NOT_FOUND"),
    ]
    for method, path, code in not_found:
        r = client.request(method, path, headers=h)
        assert (r.status_code, r.json()["error"]) == (404, code), (method, path)
    # writes into someone else's data look the same
    r = client.post("/api/conversations", headers=h, json={"connection_id": conn})
    assert r.json()["error"] == "CONNECTION_NOT_FOUND"
    r = client.post(f"/api/conversations/{conv}/messages", headers=h, json={"content": "hi"})
    assert r.json()["error"] == "CONVERSATION_NOT_FOUND"
    r = client.post(f"/api/proposals/{prop}/decision", headers=h, json={"decision": "approve"})
    assert r.json()["error"] == "PROPOSAL_NOT_FOUND"
    r = client.post(f"/api/proposals/{prop}/revise", headers=h, json={"params": {}})
    assert r.json()["error"] == "PROPOSAL_NOT_FOUND"
    r = client.post(f"/api/proposals/{prop}/rollback", headers=h)
    assert r.json()["error"] == "PROPOSAL_NOT_FOUND"
    r = client.patch(f"/api/connections/{conn}", headers=h, json={"name": "mine now"})
    assert r.json()["error"] == "CONNECTION_NOT_FOUND"
    # and nothing of A's changed
    assert (
        client.get(f"/api/connections/{conn}", headers=bearer(owned_by_a["user"])).status_code
        == 200
    )


def test_decisions_record_who_made_them(client, owned_by_a):
    r = client.post(
        f"/api/proposals/{owned_by_a['prop']}/decision",
        headers=bearer(owned_by_a["user"]),
        json={"decision": "reject"},
    )
    assert r.status_code == 200, r.text
    last = r.json()["data"]["proposal"]["history"][-1]
    assert last["status"] == "REJECTED" and last["by"] == owned_by_a["user"]


def test_jobs_belong_to_the_conversation_owner():
    from app.worker import new_job

    conv = Conversation(user_id="user-a", connection_id="conn_x")
    assert new_job(conv, "q").user_id == "user-a"


def test_store_listings_are_per_user(store):
    users = [f"user-{uuid.uuid4().hex[:8]}" for _ in range(2)]  # the SQLite test DB is shared
    for uid in users:
        conn = store.create_connection(
            Connection(user_id=uid, name=uid, type="access_key", region="ap-southeast-1")
        )
        conv = store.create_conversation(Conversation(user_id=uid, connection_id=conn.id))
        store.create_proposal(
            Proposal(user_id=uid, conversation_id=conv.id, connection_id=conn.id, action="x")
        )
    for uid in users:
        assert [c.user_id for c in store.list_connections(uid)] == [uid]
        assert [c.user_id for c in store.list_conversations(user_id=uid)] == [uid]
        assert [p.user_id for p in store.list_proposals(user_id=uid)] == [uid]
    # background work (no user) still sees everyone's
    assert {c.user_id for c in store.list_connections()} >= set(users)
    assert {p.user_id for p in store.list_proposals()} >= set(users)


def test_rows_from_before_sign_in_belong_to_the_local_user(tmp_path):
    from sqlalchemy import create_engine, text

    from app.storage.db import add_missing_columns, backfill_owner

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE "connection" (id VARCHAR PRIMARY KEY, name VARCHAR)'))
        c.execute(text("INSERT INTO \"connection\" VALUES ('conn_old', 'old')"))
    assert "connection.user_id" in add_missing_columns(engine)
    backfill_owner(engine)
    with engine.begin() as c:
        assert c.execute(text('SELECT user_id FROM "connection"')).scalar() == "local"
