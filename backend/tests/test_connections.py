from tests.conftest import FAKE_KEY, FAKE_SECRET, REGION


def test_create_and_verify_access_key(client, aws):
    r = client.post(
        "/api/connections",
        json={
            "type": "access_key",
            "name": "Lab",
            "region": REGION,
            "access_key_id": FAKE_KEY,
            "secret_access_key": FAKE_SECRET,
        },
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["status"] == "pending"
    assert data["access_key_id_masked"] == "AKIA****MPLE"
    assert "secret_access_key" not in data
    assert "access_key_id" not in data

    v = client.post(f"/api/connections/{data['id']}/verify")
    assert v.status_code == 200
    body = v.json()
    assert body["message"] == "Connection verified"
    assert body["data"]["status"] == "connected"
    assert body["data"]["account_id"] == "123456789012"

    got = client.get(f"/api/connections/{data['id']}").json()["data"]
    assert got["status"] == "connected"
    assert got["account_id"] == "123456789012"
    assert got["last_verified_at"] is not None


def test_verify_failure_marks_failed(client):
    r = client.post(
        "/api/connections",
        json={
            "type": "access_key",
            "name": "Broken",
            "region": REGION,
            "access_key_id": "AKIAAAAAAAAAAAAAAAAA",
            "secret_access_key": "x" * 40,
        },
    )
    conn_id = r.json()["data"]["id"]
    # No moto here -> real botocore call fails on bad credentials / no network.
    v = client.post(f"/api/connections/{conn_id}/verify").json()
    assert v["status_code"] == 200
    assert v["data"]["status"] == "failed"
    assert v["data"]["error"]
    assert client.get(f"/api/connections/{conn_id}").json()["data"]["status"] == "failed"


def test_role_connection_cloudformation(client, aws):
    r = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "Prod",
            "region": REGION,
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
        },
    )
    data = r.json()["data"]
    assert data["external_id"].startswith("autoaws-")

    cf = client.get(f"/api/connections/{data['id']}/cloudformation").json()["data"]
    assert cf["stack_name"] == "AutoAWSReadOnlyRole"
    assert cf["external_id"] == data["external_id"]
    yaml = cf["template_yaml"]
    assert "sts:ExternalId" in yaml
    assert "ec2:DescribeRouteTables" in yaml
    assert "Effect: Deny" in yaml and "s3:GetObject*" in yaml
    # never grant a write action
    for verb in ("Create", "Delete", "Modify", "Put", "Terminate"):
        assert f":{verb}" not in yaml


def test_cloudformation_rejected_for_access_key(client, connection):
    body = client.get(f"/api/connections/{connection['id']}/cloudformation").json()
    assert body["status_code"] == 400
    assert body["error"] == "VALIDATION_ERROR"


def test_assume_role_with_moto(client, aws):
    """Role connection end-to-end: moto's STS honours AssumeRole for any role ARN."""
    iam = aws.client("iam")
    iam.create_role(RoleName="AutoAWSReadOnly", AssumeRolePolicyDocument="{}")
    r = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "Prod",
            "region": REGION,
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
            "external_id": "autoaws-test",
        },
    )
    conn_id = r.json()["data"]["id"]
    v = client.post(f"/api/connections/{conn_id}/verify").json()
    assert v["data"]["status"] == "connected", v
    assert "assumed-role/AutoAWSReadOnly" in v["data"]["arn"]


def test_list_and_delete(client, connection):
    ids = [c["id"] for c in client.get("/api/connections").json()["data"]]
    assert connection["id"] in ids
    d = client.delete(f"/api/connections/{connection['id']}").json()
    assert d == {"status_code": 200, "message": "Connection deleted", "data": None}
    assert client.get(f"/api/connections/{connection['id']}").status_code == 404


def test_connection_setup_returns_only_public_configuration(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "platform_aws_account_id", "111122223333")
    response = client.get("/api/connections/setup")
    assert response.status_code == 200
    assert response.json() == {
        "status_code": 200,
        "message": "OK",
        "data": {"account_id": "111122223333", "role_name": "AutoAWSReadOnly"},
    }


def test_connection_setup_hides_missing_or_invalid_account(client, monkeypatch):
    from app.config import get_settings

    for account in ("", "not-an-account", "12345678901"):
        monkeypatch.setattr(get_settings(), "platform_aws_account_id", account)
        data = client.get("/api/connections/setup").json()["data"]
        assert data == {"account_id": None, "role_name": "AutoAWSReadOnly"}


def test_cloudformation_preview_before_connection_is_saved(client, monkeypatch):
    import yaml

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "platform_aws_account_id", "111122223333")
    before = client.get("/api/connections").json()["data"]
    result = client.post(
        "/api/connections/cloudformation-preview",
        json={
            "external_id": "autoaws-before-save",
        },
    )
    assert result.status_code == 200
    info = result.json()["data"]
    assert info["external_id"] == "autoaws-before-save"
    assert info["platform_account_id"] == "111122223333"
    assert info["role_name"] == "AutoAWSReadOnly"
    template = info["template_yaml"]
    assert yaml.compose(template) is not None
    assert "Default: 'autoaws-before-save'" in template
    assert "Default: '111122223333'" in template
    assert "ec2:DescribeRegions" in template
    assert "sts:GetCallerIdentity" in template
    assert "Effect: Deny" in template
    assert "secretsmanager:GetSecretValue" in template
    assert client.get("/api/connections").json()["data"] == before
    changed = client.post(
        "/api/connections/cloudformation-preview",
        json={
            "external_id": "autoaws-changed",
        },
    ).json()["data"]["template_yaml"]
    assert "autoaws-changed" in changed and "autoaws-before-save" not in changed


def test_cloudformation_preview_requires_configured_account_and_valid_external_id(
    client, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "platform_aws_account_id", "")
    result = client.post(
        "/api/connections/cloudformation-preview",
        json={
            "external_id": "autoaws-example",
        },
    )
    assert result.status_code == 503
    assert result.json()["error"] == "CONNECTION_SETUP_UNAVAILABLE"
    for value in ("", "x", "bad'quote", "bad\nnewline"):
        response = client.post(
            "/api/connections/cloudformation-preview", json={"external_id": value}
        )
        assert response.status_code == 422
        assert response.json()["error"] == "VALIDATION_ERROR"
