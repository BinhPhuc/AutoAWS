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
    from app.api import connections as connections_api
    from app.aws.credentials import CredentialError

    def rejected(_session):
        raise CredentialError("InvalidClientTokenId: The security token included is invalid")

    # No network: simulate AWS rejecting the credentials.
    monkeypatch.setattr(connections_api, "verify_session", rejected)
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
