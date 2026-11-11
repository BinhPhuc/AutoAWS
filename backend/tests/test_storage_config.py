"""Deployment storage selection and externally provisioned DynamoDB tables."""

from unittest.mock import Mock

import boto3
import pytest
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from app.config import Settings
from app.storage import store as storage
from app.storage.dynamo import DynamoStore, ensure_table
from app.storage.models import Conversation
from tests.conftest import REGION


def test_storage_defaults_to_externally_managed_dynamodb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("DYNAMODB_CREATE_TABLE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.storage_backend == "dynamodb"
    assert settings.dynamodb_create_table is False


@pytest.fixture
def deployed_storage(
    aws: boto3.Session, monkeypatch: pytest.MonkeyPatch
) -> tuple[BaseClient, Settings]:
    client = aws.client("dynamodb")
    settings = Settings(
        _env_file=None,
        storage_backend="dynamodb",
        dynamodb_table="autoaws-deployed",
        dynamodb_region=REGION,
        dynamodb_endpoint_url="",
        dynamodb_create_table=False,
    )
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "dynamodb_client", lambda: client)
    # A deployment must neither create a table nor initialize SQLite.
    monkeypatch.setattr(storage, "init_db", Mock(side_effect=AssertionError("SQLite initialized")))
    monkeypatch.setattr(storage, "ensure_table", Mock(side_effect=AssertionError("Table created")))
    return client, settings


def test_existing_dynamodb_table_is_used_without_sqlite(
    deployed_storage: tuple[BaseClient, Settings],
) -> None:
    client, settings = deployed_storage
    ensure_table(client, settings.dynamodb_table)

    storage.init_storage()
    with storage.open_store() as store:
        assert isinstance(store, DynamoStore)
        conv = store.create_conversation(Conversation(connection_id="conn_demo"))
    with storage.open_store() as store:
        saved = store.get_conversation(conv.id)
        assert saved is not None and saved.connection_id == "conn_demo"


def test_missing_deployed_table_fails_startup(
    deployed_storage: tuple[BaseClient, Settings],
) -> None:
    with pytest.raises(ClientError) as error:
        storage.init_storage()
    assert error.value.response["Error"]["Code"] == "ResourceNotFoundException"


def test_dynamodb_access_denied_fails_startup(
    deployed_storage: tuple[BaseClient, Settings],
) -> None:
    client, settings = deployed_storage
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "describe_table",
            service_error_code="AccessDeniedException",
            expected_params={"TableName": settings.dynamodb_table},
        )
        with pytest.raises(ClientError) as error:
            storage.init_storage()
    assert error.value.response["Error"]["Code"] == "AccessDeniedException"


def test_missing_table_name_fails_before_aws_call(
    deployed_storage: tuple[BaseClient, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, settings = deployed_storage
    settings.dynamodb_table = " "
    client_factory = Mock()
    monkeypatch.setattr(storage, "dynamodb_client", client_factory)
    with pytest.raises(ValueError, match="DYNAMODB_TABLE must be set"):
        storage.init_storage()
    client_factory.assert_not_called()


@pytest.mark.parametrize("endpoint", ["", "http://localhost:4566"])
def test_dynamodb_client_uses_configured_region_and_endpoint(
    monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    settings = Settings(
        _env_file=None,
        dynamodb_region="eu-west-1",
        dynamodb_endpoint_url=endpoint,
        platform_aws_profile="",
    )
    session = Mock()
    session.region_name = REGION
    session_factory = Mock(return_value=session)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setattr(storage.boto3, "Session", session_factory)
    storage.dynamodb_client.cache_clear()
    try:
        assert storage.dynamodb_client() is session.client.return_value
        session_factory.assert_called_once_with(profile_name=None)
        session.client.assert_called_once_with(
            "dynamodb", region_name="eu-west-1", endpoint_url=endpoint or None
        )
    finally:
        storage.dynamodb_client.cache_clear()
