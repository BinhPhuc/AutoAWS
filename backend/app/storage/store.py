"""Pick the storage backend (STORAGE_BACKEND) and hand out one Store per request.

DynamoDB lives in the AutoAWS platform account (docs/SYSTEM_OVERVIEW.md §7), so it uses
the platform credentials (boto3 default chain / PLATFORM_AWS_PROFILE), never a user's.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

import boto3
from botocore.client import BaseClient
from fastapi import Depends
from sqlmodel import Session, select

from app.auth import LOCAL_USER, User, current_user
from app.config import get_settings
from app.storage.base import Store
from app.storage.db import get_engine, init_db
from app.storage.dynamo import DynamoStore, ensure_table
from app.storage.models import Proposal
from app.storage.sql import SqlStore


def remediation_owners() -> list[str]:
    """Startup maintenance only: enumerate owners, then recover within each scoped store."""
    settings = get_settings()
    if settings.storage_backend == "sqlite":
        with Session(get_engine()) as session:
            return [uid for uid in session.exec(select(Proposal.user_id).distinct()) if uid]
    owners: set[str] = set()
    for page in (
        dynamodb_client()
        .get_paginator("scan")
        .paginate(
            TableName=settings.dynamodb_table,
            ProjectionExpression="user_id",
            FilterExpression="entity = :entity",
            ExpressionAttributeValues={":entity": {"S": "proposal"}},
        )
    ):
        owners.update(i["user_id"]["S"] for i in page.get("Items", []) if "user_id" in i)
    return sorted(owners)


@lru_cache
def dynamodb_client() -> BaseClient:
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
        if not settings.dynamodb_table.strip():
            raise ValueError("DYNAMODB_TABLE must be set when STORAGE_BACKEND=dynamodb")
        if settings.dynamodb_create_table:
            ensure_table(dynamodb_client(), settings.dynamodb_table, settings.dynamodb_kms_key_id)
        else:
            # Fail at startup on missing tables or permissions; never fall back to SQLite.
            dynamodb_client().describe_table(TableName=settings.dynamodb_table)
    else:
        init_db()


def get_store(user: User = Depends(current_user)) -> Iterator[Store]:
    """FastAPI dependency: the Store for this request."""
    with open_store(user.user_id) as store:
        yield store


@contextmanager
def open_store(user_id: str = LOCAL_USER) -> Iterator[Store]:
    """A tenant-scoped Store for requests and trusted background work."""
    if not user_id or "#" in user_id:
        raise ValueError("A valid user_id is required")
    settings = get_settings()
    if settings.storage_backend == "dynamodb":
        yield DynamoStore(dynamodb_client(), settings.dynamodb_table, user_id)
        return
    with Session(get_engine()) as session:
        yield SqlStore(session, user_id)
