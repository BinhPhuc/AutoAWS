"""Local startup must expose .env credentials to AWS SDKs without overriding the host."""

from pathlib import Path

import pytest

from app.aws.credentials import platform_session
from app.config import get_settings
from app.storage.store import dynamodb_client


@pytest.mark.parametrize("host_credentials", [False, True])
def test_dotenv_credentials_reach_aws_sdks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host_credentials: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    values = {
        "AWS_ACCESS_KEY_ID": "file-test-key",
        "AWS_SECRET_ACCESS_KEY": "file-test-secret",
        "AWS_SESSION_TOKEN": "file-test-token",
        "PLATFORM_AWS_PROFILE": "",
        "DYNAMODB_REGION": "ap-southeast-1",
        "DYNAMODB_TABLE": "autoaws-test",
    }
    (tmp_path / ".env").write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8"
    )
    for key in values:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    if host_credentials:
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            monkeypatch.setenv(key, values[key].replace("file-", "host-"))

    get_settings.cache_clear()
    dynamodb_client.cache_clear()
    try:
        assert get_settings().dynamodb_table == "autoaws-test"
        sources = (
            platform_session().get_credentials(),
            dynamodb_client()._request_signer._credentials,
        )
        prefix = "host" if host_credentials else "file"
        for credentials in sources:
            assert credentials is not None
            frozen = credentials.get_frozen_credentials()
            assert frozen.access_key == f"{prefix}-test-key"
            assert frozen.secret_key == f"{prefix}-test-secret"
            assert frozen.token == f"{prefix}-test-token"
    finally:
        get_settings.cache_clear()
        dynamodb_client.cache_clear()
