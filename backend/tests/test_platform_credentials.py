"""Local dotenv credentials work without shared AWS files or exported credentials."""

from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from app.aws import credentials
from app.config import Settings
from app.llm.base import LLMError
from tests.conftest import FAKE_KEY, FAKE_SECRET, REGION


@pytest.fixture
def dotenv_settings(tmp_path, monkeypatch):
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "PLATFORM_AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    path = tmp_path / ".env"
    path.write_text(
        f"AWS_ACCESS_KEY_ID={FAKE_KEY}\nAWS_SECRET_ACCESS_KEY={FAKE_SECRET}\n"
        f"AWS_DEFAULT_REGION={REGION}\nPLATFORM_AWS_PROFILE=unused-profile\n"
    )
    settings = Settings(_env_file=path)
    monkeypatch.setattr(credentials, "get_settings", lambda: settings)
    return settings


def test_dotenv_session_without_host_configuration(dotenv_settings):
    session = credentials.platform_session()
    loaded = session.get_credentials().get_frozen_credentials()
    assert loaded.access_key == FAKE_KEY
    assert loaded.secret_key == FAKE_SECRET
    assert loaded.token is None
    assert session.region_name == REGION
    assert FAKE_KEY not in repr(dotenv_settings)
    assert FAKE_SECRET not in repr(dotenv_settings)


def test_temporary_credentials_include_session_token(dotenv_settings):
    dotenv_settings.aws_session_token = SecretStr("temporary-test-token")
    session = credentials.platform_session()
    assert session.get_credentials().token == "temporary-test-token"
    assert "temporary-test-token" not in repr(dotenv_settings)


@pytest.mark.parametrize("missing", ["aws_access_key_id", "aws_secret_access_key"])
def test_partial_dotenv_credentials_fail_without_host_fallback(dotenv_settings, missing):
    setattr(dotenv_settings, missing, SecretStr(""))
    with pytest.raises(credentials.CredentialError, match="Set both AWS_ACCESS_KEY_ID") as exc:
        credentials.platform_session()
    assert FAKE_SECRET not in str(exc.value)
    assert FAKE_KEY not in str(exc.value)


def test_assume_role_using_only_dotenv(client, aws, dotenv_settings):
    response = client.post(
        "/api/connections",
        json={
            "type": "role",
            "name": "dotenv-role",
            "region": REGION,
            "role_arn": "arn:aws:iam::123456789012:role/AutoAWSReadOnly",
            "external_id": "autoaws-dotenv",
        },
    )
    conn_id = response.json()["data"]["id"]
    result = client.post(f"/api/connections/{conn_id}/verify").json()["data"]
    assert result["status"] == "connected"
    assert "assumed-role/AutoAWSReadOnly" in result["arn"]


def test_bedrock_uses_dotenv_session(dotenv_settings, monkeypatch):
    from app.aws.bedrock import converse

    # Keep the real session factory so this exercises the same dotenv path as AssumeRole.
    client = Mock()
    client.converse.return_value = {"stopReason": "end_turn"}
    monkeypatch.setattr("boto3.session.Session.client", lambda *args, **kwargs: client)
    assert converse(REGION, {"modelId": "test-model"})["stopReason"] == "end_turn"
    client.converse.assert_called_once_with(modelId="test-model")


def test_bedrock_reports_partial_credentials(dotenv_settings):
    from app.aws.bedrock import converse

    dotenv_settings.aws_secret_access_key = SecretStr("")
    with pytest.raises(LLMError, match="Set both AWS_ACCESS_KEY_ID"):
        converse(REGION, {"modelId": "test-model"})


def test_profile_fallback_when_no_credentials(dotenv_settings, monkeypatch):
    dotenv_settings.aws_access_key_id = SecretStr("")
    dotenv_settings.aws_secret_access_key = SecretStr("")
    factory = Mock()
    monkeypatch.setattr(credentials.boto3, "Session", factory)
    credentials.platform_session()
    factory.assert_called_once_with(profile_name="unused-profile", region_name=REGION)


def test_dotenv_location_is_independent_of_working_directory(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    assert (
        Settings.model_config["env_file"]
        == Path(credentials.__file__).resolve().parents[2] / ".env"
    )
