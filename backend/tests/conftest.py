import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

# Must be set before `app` is imported: Settings and the engine are cached singletons.
# API tests use isolated local storage; DynamoDB coverage uses moto explicitly.
os.environ["STORAGE_BACKEND"] = "sqlite"
os.environ["AUTH_MODE"] = "none"
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
# moto ignores DryRun on some EC2 writes (it would apply the change): tested separately
os.environ.setdefault("REMEDIATION_DRY_RUN", "false")

REGION = "ap-southeast-1"
FAKE_KEY = "AKIAIOSFODNN7EXAMPLE"
FAKE_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DB_PATH"] = str(path)
    return path


@pytest.fixture(scope="session")
def app(db_path):
    from app.config import get_settings
    from app.storage.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def aws():
    """Moto-backed AWS; also returns a boto3 session pointed at it."""
    with mock_aws():
        yield boto3.Session(
            aws_access_key_id=FAKE_KEY, aws_secret_access_key=FAKE_SECRET, region_name=REGION
        )


@pytest.fixture
def connection(client, aws):
    """A verified access_key connection against moto."""
    r = client.post(
        "/api/connections",
        json={
            "type": "access_key",
            "name": "moto",
            "region": REGION,
            "access_key_id": FAKE_KEY,
            "secret_access_key": FAKE_SECRET,
        },
    )
    assert r.status_code == 201, r.text
    conn = r.json()["data"]
    v = client.post(f"/api/connections/{conn['id']}/verify").json()
    assert v["data"]["status"] == "connected", v
    return conn


@pytest.fixture(params=["sqlite", "dynamodb"])
def store(request, app, aws):
    """A Store of each backend: SQLite (test DB) and DynamoDB (moto, fresh table per test)."""
    if request.param == "sqlite":
        from sqlmodel import Session

        from app.storage.db import get_engine, init_db
        from app.storage.sql import SqlStore

        init_db()
        with Session(get_engine()) as session:
            yield SqlStore(session)
    else:
        from app.storage.dynamo import DynamoStore, ensure_table

        client = aws.client("dynamodb")
        ensure_table(client, "autoaws-test")
        yield DynamoStore(client, "autoaws-test")


def ask(client, conv_id: str, content: str) -> tuple[dict, list[tuple[str, dict]]]:
    """Start a diagnosis job and return (job, [(event type, data), ...]).

    RUNTIME=local runs the job as a BackgroundTask; TestClient returns the POST response
    only after background tasks finished, so the job is already done here."""
    r = client.post(f"/api/conversations/{conv_id}/messages", json={"content": content})
    assert r.status_code == 202, r.text
    job = client.get(f"/api/jobs/{r.json()['data']['id']}").json()["data"]
    return job, [(e["type"], e["data"]) for e in job["events"]]
