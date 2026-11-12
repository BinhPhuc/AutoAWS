"""Editing a connection after it was created (docs/API_CONTRACT.md §2, PATCH)."""

from types import SimpleNamespace

from tests.conftest import REGION

ROLE = "arn:aws:iam::123456789012:role/AutoAWSReadOnly"
OTHER_ROLE = "arn:aws:iam::123456789012:role/AutoAWSReadOnly-v2"


def _role_connection(client) -> dict:
    ext_id = client.get("/api/connections/setup").json()["data"]["external_id"]
    r = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "prod",
            "region": REGION,
            "role_arn": ROLE,
            "external_id": ext_id,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _patch(client, conn_id: str, **body):
    return client.patch(f"/api/connections/{conn_id}", json=body)


def _track_assume_role(aws, monkeypatch) -> list[dict]:
    """Platform STS on moto; records every AssumeRole call."""
    from app.aws import credentials

    sts = aws.client("sts")
    original, calls = sts.assume_role, []

    def assume_role(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(sts, "assume_role", assume_role)
    monkeypatch.setattr(
        credentials, "platform_session", lambda: SimpleNamespace(client=lambda _: sts)
    )
    return calls


def test_setup_suggests_the_configured_region(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "default_region", "ap-southeast-2")
    data = client.get("/api/connections/setup").json()["data"]
    assert data["default_region"] == "ap-southeast-2"


def test_renaming_keeps_the_connection_verified(client, connection):
    r = _patch(client, connection["id"], name="Lab (renamed)")
    assert r.status_code == 200 and r.json()["message"] == "Connection updated"
    data = r.json()["data"]
    assert data["name"] == "Lab (renamed)" and data["status"] == "connected"
    assert data["region"] == REGION


def test_same_region_is_not_a_change(client, connection):
    data = _patch(client, connection["id"], region=REGION).json()["data"]
    assert data["status"] == "connected"


def test_new_region_needs_a_new_verify(client, connection):
    data = _patch(client, connection["id"], region="ap-southeast-2").json()["data"]
    assert (data["region"], data["status"], data["last_error"]) == (
        "ap-southeast-2",
        "pending",
        None,
    )
    verified = client.post(f"/api/connections/{connection['id']}/verify").json()["data"]
    assert verified["status"] == "connected"
    got = client.get(f"/api/connections/{connection['id']}").json()["data"]
    assert (got["region"], got["status"]) == ("ap-southeast-2", "connected")


def test_a_failed_connection_can_be_fixed_by_editing(client, aws, monkeypatch):
    """The case that started this: verify failed because of the region; fix it in place."""
    from app.storage.store import open_store

    conn = _role_connection(client)
    with open_store() as store:
        c = store.get_connection(conn["id"])
        c.status, c.last_error = "failed", "UnauthorizedOperation: explicit deny in an SCP"
        store.save_connection(c)
    data = _patch(client, conn["id"], region="ap-southeast-2").json()["data"]
    assert (data["status"], data["last_error"]) == ("pending", None)


def test_changing_the_role_assumes_the_new_role(client, aws, monkeypatch):
    calls = _track_assume_role(aws, monkeypatch)
    conn = _role_connection(client)
    from app.aws.credentials import resolve_session
    from app.storage.store import open_store

    def session_for_conn():
        with open_store() as store:
            return resolve_session(store.get_connection(conn["id"]))

    session_for_conn()
    session_for_conn()  # cached: no second AssumeRole
    assert [c["RoleArn"] for c in calls] == [ROLE]

    data = _patch(client, conn["id"], role_arn=OTHER_ROLE).json()["data"]
    assert data["role_arn"] == OTHER_ROLE and data["status"] == "pending"
    assert data["external_id"] == conn["external_id"]  # the trust policy still matches
    session_for_conn()
    assert [c["RoleArn"] for c in calls] == [ROLE, OTHER_ROLE]


def test_a_changed_region_is_never_served_from_the_old_session(client, aws, monkeypatch):
    """Even if the cache were not cleared, the cache key holds role, External ID and region."""
    from app.aws import credentials
    from app.storage.store import open_store

    calls = _track_assume_role(aws, monkeypatch)
    conn = _role_connection(client)
    with open_store() as store:
        c = store.get_connection(conn["id"])
    first = credentials.resolve_session(c)
    c.region = "ap-southeast-2"  # changed without going through the API
    second = credentials.resolve_session(c)
    assert len(calls) == 2 and second is not first
    assert second.region_name == "ap-southeast-2"


def test_type_and_external_id_cannot_be_changed(client, aws):
    conn = _role_connection(client)
    other_id = client.get("/api/connections/setup").json()["data"]["external_id"]
    data = _patch(client, conn["id"], name="x", type="access_key", external_id=other_id).json()[
        "data"
    ]
    assert data["type"] == "role" and data["external_id"] == conn["external_id"]


def test_role_arns_only_on_role_connections(client, connection):
    for field in ("role_arn", "remediation_role_arn"):
        r = _patch(client, connection["id"], **{field: OTHER_ROLE})
        assert (r.status_code, r.json()["error"]) == (400, "VALIDATION_ERROR"), field


def test_required_fields_cannot_be_cleared(client, aws):
    conn = _role_connection(client)
    for field in ("name", "region", "role_arn"):
        r = _patch(client, conn["id"], **{field: None})
        assert (r.status_code, r.json()["error"]) == (422, "VALIDATION_ERROR"), field
    # the remediation role is optional: null turns remediation off
    r = _patch(client, conn["id"], remediation_role_arn=None)
    assert r.status_code == 200 and r.json()["data"]["remediation_enabled"] is False


def test_bad_values_are_refused(client, aws):
    conn = _role_connection(client)
    for body in ({"region": "Singapore"}, {"role_arn": "not-an-arn"}, {"name": ""}):
        r = _patch(client, conn["id"], **body)
        assert r.status_code == 422, body
    assert client.get(f"/api/connections/{conn['id']}").json()["data"]["name"] == "prod"


def test_unknown_connection(client):
    r = _patch(client, "conn_missing", name="x")
    assert (r.status_code, r.json()["error"]) == (404, "CONNECTION_NOT_FOUND")


def test_a_cached_session_must_outlive_a_whole_job(client, aws, monkeypatch):
    """A job keeps the session it got at the start for up to MAX_AGENT_SECONDS: a session
    about to expire is not reused (it used to be, down to 60 s, and expired mid-job)."""
    from datetime import UTC, datetime, timedelta

    from app.aws import credentials
    from app.config import get_settings
    from app.storage.store import open_store

    monkeypatch.setattr(get_settings(), "max_agent_seconds", 240)
    calls = _track_assume_role(aws, monkeypatch)
    conn = _role_connection(client)
    with open_store() as store:
        c = store.get_connection(conn["id"])
    first = credentials.resolve_session(c)
    assert credentials.resolve_session(c) is first  # fresh: reused
    session, _, key = credentials._role_cache[c.id]
    soon = datetime.now(UTC) + timedelta(seconds=200)  # > 60 s left, < one job
    credentials._role_cache[c.id] = (session, soon, key)
    assert credentials.resolve_session(c) is not first
    assert len(calls) == 2
