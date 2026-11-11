"""External IDs are issued by the server and bound to one user (confused deputy).

Scenario guarded here: B's role trusts AutoAWS with External ID X. A (another AutoAWS user)
learns B's Role ARN and X. A must not be able to create a connection that carries X, or
AutoAWS would assume B's role on A's behalf.
"""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth, external_id
from app.config import get_settings

ROLE_B = "arn:aws:iam::222222222222:role/AutoAWSReadOnly"
POOL = "ap-southeast-1_ExtIdPool"
ISSUER = f"https://cognito-idp.ap-southeast-1.amazonaws.com/{POOL}"
CLIENT_ID = "extid-web"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _as(sub: str) -> dict:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": sub,
            "iss": ISSUER,
            "client_id": CLIENT_ID,
            "token_use": "access",
            "iat": now,
            "exp": now + 3600,
        },
        KEY,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def users(monkeypatch):
    """Two signed-in users (Cognito mode, no JWKS fetch)."""
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "cognito")
    monkeypatch.setattr(s, "cognito_user_pool_id", POOL)
    monkeypatch.setattr(s, "cognito_client_id", CLIENT_ID)
    monkeypatch.setattr(s, "cognito_domain", "https://extid.auth.ap-southeast-1.amazoncognito.com")
    monkeypatch.setattr(auth, "signing_key", lambda _t, _s: KEY.public_key())
    tag = uuid.uuid4().hex[:8]  # the SQLite test DB is shared between tests
    return _as(f"user-a-{tag}"), _as(f"user-b-{tag}")


def _issue(client, headers) -> str:
    return client.get("/api/connections/setup", headers=headers).json()["data"]["external_id"]


def _create(client, headers, ext_id: str | None, role_arn: str = ROLE_B):
    body = {"type": "role", "name": "conn", "region": "ap-southeast-1", "role_arn": role_arn}
    if ext_id is not None:
        body["external_id"] = ext_id
    return client.post("/api/connections", headers=headers, json=body)


def test_ids_are_fresh_and_verify_only_for_their_user():
    a = external_id.issue("user-a")
    assert a != external_id.issue("user-a")
    assert external_id.issued_to(a, "user-a")
    assert not external_id.issued_to(a, "user-b")
    tampered = a[:-1] + ("0" if a[-1] != "0" else "1")
    for bad in (tampered, "autoaws-test", "", "autoaws-" + "0" * 16 + "-" + "0" * 24):
        assert not external_id.issued_to(bad, "user-a"), bad


def test_another_users_external_id_is_refused(client, users):
    """The confused deputy attempt: A knows B's Role ARN and External ID."""
    a, b = users
    b_id = _issue(client, b)
    assert _create(client, b, b_id).status_code == 201  # B connects normally
    r = _create(client, a, b_id)  # A replays B's ID
    assert (r.status_code, r.json()["error"]) == (400, "EXTERNAL_ID_INVALID")


def test_an_id_b_was_issued_but_never_used_is_refused_for_a(client, users):
    """Not only a uniqueness check: an ID shown to B (role created, not saved yet, or the
    connection deleted later) still cannot be claimed by A."""
    a, b = users
    b_id = _issue(client, b)
    r = _create(client, a, b_id)
    assert r.json()["error"] == "EXTERNAL_ID_INVALID"


@pytest.mark.parametrize("chosen", ["autoaws-test", "my-own-id", "autoaws-1234"])
def test_client_chosen_ids_are_refused(client, users, chosen):
    a, _ = users
    assert _create(client, a, chosen).json()["error"] == "EXTERNAL_ID_INVALID"
    preview = client.post(
        "/api/connections/cloudformation-preview", headers=a, json={"external_id": chosen}
    )
    assert preview.json()["error"] == "EXTERNAL_ID_INVALID"


def test_the_issued_id_is_kept_and_cannot_be_used_twice(client, users):
    a, _ = users
    ext_id = _issue(client, a)
    first = _create(client, a, ext_id)
    assert first.status_code == 201 and first.json()["data"]["external_id"] == ext_id
    again = _create(client, a, ext_id, role_arn="arn:aws:iam::333333333333:role/AutoAWSReadOnly")
    assert (again.status_code, again.json()["error"]) == (409, "EXTERNAL_ID_IN_USE")


def test_without_an_id_the_server_issues_one(client, users):
    a, _ = users
    conn = _create(client, a, None).json()["data"]
    assert conn["external_id"].startswith("autoaws-")
    assert _create(client, a, conn["external_id"]).json()["error"] == "EXTERNAL_ID_IN_USE"


def test_a_new_secret_invalidates_old_ids(monkeypatch):
    from pydantic import SecretStr

    s = get_settings()
    monkeypatch.setattr(s, "external_id_secret", SecretStr("first-secret"))
    old = external_id.issue("user-a")
    monkeypatch.setattr(s, "external_id_secret", SecretStr("second-secret"))
    assert not external_id.issued_to(old, "user-a")


def test_deployments_must_set_their_own_key(monkeypatch):
    from pydantic import SecretStr

    s = get_settings()
    monkeypatch.setattr(s, "external_id_secret", SecretStr(""))
    monkeypatch.setattr(s, "auth_mode", "none")
    monkeypatch.setattr(s, "runtime", "local")
    external_id.check_settings(s)  # local dev: the development key is allowed
    for field, value in (("auth_mode", "cognito"), ("runtime", "lambda")):
        monkeypatch.setattr(s, field, value)
        with pytest.raises(RuntimeError, match="EXTERNAL_ID_SECRET"):
            external_id.check_settings(s)
        monkeypatch.setattr(s, "auth_mode", "none")
        monkeypatch.setattr(s, "runtime", "local")
    monkeypatch.setattr(s, "external_id_secret", SecretStr("a-long-random-value"))
    monkeypatch.setattr(s, "auth_mode", "cognito")
    external_id.check_settings(s)
