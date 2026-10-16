"""Response envelope contract (docs/API_CONTRACT.md §0)."""

ERROR_KEYS = {"status_code", "message", "error", "path", "timestamp"}


def test_health_envelope(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status_code", "message", "data"}
    assert body["status_code"] == 200
    assert body["data"]["status"] == "ok"
    assert body["data"]["llm_provider"] == "mock"


def test_not_found_envelope(client):
    r = client.get("/api/connections/conn_doesnotexist")
    assert r.status_code == 404
    body = r.json()
    assert set(body) == ERROR_KEYS
    assert body["error"] == "CONNECTION_NOT_FOUND"
    assert body["path"] == "/api/connections/conn_doesnotexist"
    assert "data" not in body


def test_unknown_route_envelope(client):
    body = client.get("/api/nope").json()
    assert set(body) == ERROR_KEYS
    assert body["status_code"] == 404


def test_validation_envelope(client):
    r = client.post("/api/connections", json={"type": "role", "name": "x", "region": "r"})
    assert r.status_code == 422
    body = r.json()
    assert set(body) == ERROR_KEYS
    assert body["error"] == "VALIDATION_ERROR"
    assert body["message"].startswith("Invalid request")


def test_checklists_not_implemented(client):
    body = client.post("/api/checklists/runs").json()
    assert body["status_code"] == 501
    assert body["error"] == "NOT_IMPLEMENTED"
