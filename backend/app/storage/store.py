"""Pick the storage backend (STORAGE_BACKEND) and hand out one Store per request.

DynamoDB lives in the AutoAWS platform account (docs/SYSTEM_OVERVIEW.md §7), so it uses
the platform credentials (boto3 default chain / PLATFORM_AWS_PROFILE), never a user's.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

import boto3
from sqlmodel import Session

from app.config import get_settings
from app.storage.base import Store
from app.storage.db import get_engine, init_db
from app.storage.dynamo import DynamoStore, ensure_table
from app.storage.sql import SqlStore


@lru_cache
def dynamodb_client():
    settings = get_settings()
    session = boto3.Session(profile_name=settings.platform_aws_profile or None)
    return session.client(
        "dynamodb",
        region_name=settings.dynamodb_region or session.region_name or "ap-southeast-1",
        endpoint_url=settings.dynamodb_endpoint_url or None,
    )


def init_storage() -> None:
    settings = get_settings()
    if settings.storage_backend == "dynamodb":
        if settings.dynamodb_create_table:
            ensure_table(dynamodb_client(), settings.dynamodb_table, settings.dynamodb_kms_key_id)
    else:
        init_db()


def get_store() -> Iterator[Store]:
    """FastAPI dependency: the Store for this request."""
    settings = get_settings()
    if settings.storage_backend == "dynamodb":
        yield DynamoStore(dynamodb_client(), settings.dynamodb_table)
        return
    with Session(get_engine()) as session:
        yield SqlStore(session)


@contextmanager
def open_store() -> Iterator[Store]:
    """A Store outside a request (background execution of an approved proposal)."""
    yield from get_store()
