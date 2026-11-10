import pytest

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


def test_verify_failure_marks_failed(client, monkeypatch):
    from app import worker
    from app.aws.credentials import CredentialError

    def rejected(_session):
        raise CredentialError("InvalidClientTokenId: The security token included is invalid")

    # No network: simulate AWS rejecting the credentials.
    monkeypatch.setattr(worker, "verify_session", rejected)
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
    # The read-only role never gets a write action ...
    read_part, remediation_part = yaml.split("  AutoAWSRemediationRole:", 1)
    for verb in ("Create", "Delete", "Modify", "Put", "Terminate", "Associate", "Authorize"):
        assert f":{verb}" not in read_part
    # ... writes live only in the optional remediation role (off by default), exactly the
    # catalogue's actions, plus an explicit Deny of IAM / stop / terminate.
    from app.aws.remediation.catalog import all_write_actions

    assert "Default: 'false'" in yaml and "Condition: RemediationEnabled" in remediation_part
    import re

    granted = set(
        re.findall(
            r"^\s+- ([a-z0-9-]+:[A-Za-z]+)$", remediation_part.split("DenyDangerous")[0], re.M
        )
    )
    assert granted == set(all_write_actions())
    assert "iam:*" in remediation_part and "ec2:TerminateInstances" in remediation_part


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


def test_preview_save_and_verify_keep_the_same_external_id(client, aws, monkeypatch):
    """Moto does not enforce trust policies, so explicitly check the AssumeRole input."""
    from types import SimpleNamespace

    from app.aws import credentials
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "platform_aws_account_id", "111122223333")
    external_id = "autoaws-onboarding-test"
    preview = client.post(
        "/api/connections/cloudformation-preview", json={"external_id": external_id}
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["external_id"] == external_id
    assert f"Default: '{external_id}'" in preview.json()["data"]["template_yaml"]

    conn = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "Prepared role",
            "region": REGION,
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
            "external_id": external_id,
        },
    ).json()["data"]
    assert conn["external_id"] == external_id
    sts = aws.client("sts")
    original = sts.assume_role
    calls = []

    def check_external_id(**kwargs):
        assert kwargs["ExternalId"] == external_id
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(sts, "assume_role", check_external_id)
    monkeypatch.setattr(
        credentials, "platform_session", lambda: SimpleNamespace(client=lambda _: sts)
    )
    for _ in range(2):
        verified = client.post(f"/api/connections/{conn['id']}/verify").json()["data"]
        assert verified["status"] == "connected"
    assert len(calls) == 2
    assert (
        client.get(f"/api/connections/{conn['id']}/cloudformation").json()["data"]["external_id"]
        == external_id
    )


@pytest.mark.parametrize(
    "external_id", ["", "x", "has space", "bad'quote", "x\nInjected", "x" * 1225]
)
def test_external_id_is_validated_for_preview_and_create(client, external_id):
    assert (
        client.post(
            "/api/connections/cloudformation-preview", json={"external_id": external_id}
        ).status_code
        == 422
    )
    r = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "Invalid ID",
            "region": REGION,
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
            "external_id": external_id,
        },
    )
    assert r.status_code == 422


def test_setup_and_preview_use_configured_platform_roles(client, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "platform_aws_account_id", "111122223333")
    principals = [
        f"arn:aws:iam::111122223333:role/autoaws-{name}"
        for name in ("agent-worker", "action-executor")
    ]
    monkeypatch.setattr(settings, "platform_agent_role_arn", principals[0])
    monkeypatch.setattr(settings, "platform_executor_role_arn", principals[1])
    setup = client.get("/api/connections/setup")
    assert setup.status_code == 200
    assert setup.json()["data"] == {
        "account_id": "111122223333",
        "role_name": "AutoAWSReadOnly",
        "trust_principals": principals,
    }
    template = client.post(
        "/api/connections/cloudformation-preview", json={"external_id": "autoaws-test"}
    ).json()["data"]["template_yaml"]
    assert "role/autoaws-agent-worker" in template and "role/autoaws-action-executor" in template


def test_setup_unavailable_without_platform_account(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "platform_aws_account_id", "")
    assert client.get("/api/connections/setup").json()["data"]["account_id"] is None
    response = client.post(
        "/api/connections/cloudformation-preview", json={"external_id": "autoaws-test"}
    )
    assert response.status_code == 503
    assert response.json()["error"] == "CONNECTION_SETUP_UNAVAILABLE"


def test_setup_endpoints_require_sign_in(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "auth_mode", "cognito")
    assert client.get("/api/connections/setup").status_code == 401
    assert (
        client.post(
            "/api/connections/cloudformation-preview", json={"external_id": "autoaws-test"}
        ).status_code
        == 401
    )
